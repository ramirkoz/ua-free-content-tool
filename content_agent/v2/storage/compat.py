"""V2 storage compatibility boundary over the proven RC30 database.

The first V2 release keeps the RC30 schema and data intact, while adding only
small, explicit V2 behaviours that are unsafe to bolt onto the UI: history retry
and retry-aware media retention.
"""
from __future__ import annotations

import json
from typing import Any

from ...database import _iso
from ...database_v1_4_rc10 import _IMMEDIATE_PRIORITY_AT
from ...database_v1_4_rc21 import Database as Rc30Database
from ..publishing.retry import RetryBatchResult, assess_failed_target, sanitize_retry_progress


class Database(Rc30Database):
    """RC30-compatible database plus safe V2 publication recovery."""

    def media_cleanup_ready_for_group(self, group_id: int) -> bool:
        """Delete shared Drive media only after the *latest* attempt per destination succeeded.

        RC30 treated a terminal failure like a successful terminal state for media
        cleanup. That made a later manual retry impossible after an auth/network
        failure because the shared Drive object could already be gone. V2 retains
        media while any destination's latest attempt is failed or active. Once a
        retry succeeds, older failed attempts remain in history but no longer block
        cleanup.
        """
        with self.connect() as db:
            active = int(
                db.execute(
                    """
                    SELECT COUNT(*)
                    FROM publication_batches b
                    JOIN articles a ON a.id=b.article_id
                    WHERE a.group_id=? AND b.status IN ('pending','in_progress','paused')
                    """,
                    (int(group_id),),
                ).fetchone()[0]
                or 0
            )
            if active:
                return False
            rows = db.execute(
                """
                SELECT t.platform,t.status
                FROM publication_targets t
                JOIN publication_batches b ON b.id=t.batch_id
                JOIN articles a ON a.id=b.article_id
                WHERE a.group_id=? AND b.status!='cancelled'
                  AND t.id=(
                      SELECT MAX(t2.id)
                      FROM publication_targets t2
                      JOIN publication_batches b2 ON b2.id=t2.batch_id
                      JOIN articles a2 ON a2.id=b2.article_id
                      WHERE a2.group_id=a.group_id
                        AND t2.platform=t.platform
                        AND b2.status!='cancelled'
                  )
                ORDER BY t.platform
                """,
                (int(group_id),),
            ).fetchall()
        return bool(rows) and all(str(row["status"]) == "sent" for row in rows)

    def retry_failed_publications(self, group_id: int) -> RetryBatchResult:
        """Create immediate retry batches for the latest safe failed destinations.

        Successful destinations are never replayed. The original failed attempts
        remain immutable history. No editorial/AI stage is invoked: the exact saved
        payload text and current group media are reused by the normal publication
        worker. Ambiguous/partial external writes fail closed to avoid duplicates.
        """
        group_id = int(group_id)
        if group_id <= 0:
            raise ValueError("Неправильний ID матеріалу.")
        result = RetryBatchResult(group_id=group_id)
        requested_at = _iso()

        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                group_row = db.execute(
                    "SELECT id,media_file_id FROM news_groups WHERE id=?",
                    (group_id,),
                ).fetchone()
                if not group_row:
                    raise KeyError(group_id)

                # One latest attempt per concrete destination. Old failures stay in
                # history but are never retried after a newer sent/active attempt.
                rows = db.execute(
                    """
                    SELECT t.id AS target_id,t.batch_id,t.platform,t.payload_text,
                           t.status AS target_status,t.remote_id,t.last_error,t.progress_json,
                           b.status AS batch_status,b.article_id
                    FROM publication_targets t
                    JOIN publication_batches b ON b.id=t.batch_id
                    JOIN articles a ON a.id=b.article_id
                    WHERE a.group_id=? AND b.status!='cancelled'
                      AND t.id=(
                          SELECT MAX(t2.id)
                          FROM publication_targets t2
                          JOIN publication_batches b2 ON b2.id=t2.batch_id
                          JOIN articles a2 ON a2.id=b2.article_id
                          WHERE a2.group_id=a.group_id
                            AND t2.platform=t.platform
                            AND b2.status!='cancelled'
                      )
                    ORDER BY t.platform
                    """,
                    (group_id,),
                ).fetchall()

                for row in rows:
                    platform = str(row["platform"] or "")
                    if str(row["target_status"] or "") != "failed":
                        continue

                    active = db.execute(
                        """
                        SELECT 1
                        FROM publication_targets t
                        JOIN publication_batches b ON b.id=t.batch_id
                        JOIN articles a ON a.id=b.article_id
                        WHERE a.group_id=? AND t.platform=?
                          AND b.status IN ('pending','in_progress','paused')
                        LIMIT 1
                        """,
                        (group_id, platform),
                    ).fetchone()
                    if active:
                        result.blocked[platform] = "Для цієї мережі вже є активна спроба публікації."
                        continue

                    confirmed_sent = db.execute(
                        """
                        SELECT 1
                        FROM publication_targets t
                        JOIN publication_batches b ON b.id=t.batch_id
                        JOIN articles a ON a.id=b.article_id
                        WHERE a.group_id=? AND t.platform=?
                          AND b.status!='cancelled' AND t.status='sent'
                        LIMIT 1
                        """,
                        (group_id, platform),
                    ).fetchone()
                    if confirmed_sent:
                        result.blocked[platform] = "Для цієї мережі вже є підтверджена успішна публікація; стару помилку не повторюємо."
                        continue

                    assessment = assess_failed_target(row)
                    if not assessment.retryable:
                        result.blocked[platform] = assessment.reason
                        continue

                    old_target_id = int(row["target_id"])
                    old_batch_id = int(row["batch_id"])
                    progress = sanitize_retry_progress(
                        row["progress_json"],
                        requested_at=requested_at,
                        old_target_id=old_target_id,
                        old_batch_id=old_batch_id,
                    )
                    cursor = db.execute(
                        """
                        INSERT INTO publication_batches(
                            article_id,scheduled_at,status,lease_owner,lease_until,attempts,
                            cleanup_error,created_at,updated_at
                        ) VALUES(?,?,'pending',NULL,NULL,0,NULL,?,?)
                        """,
                        (int(row["article_id"]), _IMMEDIATE_PRIORITY_AT, requested_at, requested_at),
                    )
                    new_batch_id = int(cursor.lastrowid)
                    db.execute(
                        """
                        INSERT INTO publication_targets(
                            batch_id,platform,payload_text,status,remote_id,last_error,progress_json,updated_at
                        ) VALUES(?,?,?,'pending',NULL,NULL,?,?)
                        """,
                        (
                            new_batch_id,
                            platform,
                            str(row["payload_text"] or ""),
                            json.dumps(progress, ensure_ascii=False, sort_keys=True),
                            requested_at,
                        ),
                    )

                    # Annotate the immutable failed attempt so History can explain
                    # that a replacement attempt was created without changing its
                    # actual failure status or error evidence.
                    old_progress: dict[str, Any]
                    try:
                        parsed = json.loads(str(row["progress_json"] or "{}"))
                        old_progress = dict(parsed) if isinstance(parsed, dict) else {}
                    except Exception:
                        old_progress = {}
                    old_progress["retry_superseded_by_batch_id"] = new_batch_id
                    old_progress["retry_requested_at"] = requested_at
                    db.execute(
                        "UPDATE publication_targets SET progress_json=? WHERE id=?",
                        (json.dumps(old_progress, ensure_ascii=False, sort_keys=True), old_target_id),
                    )

                    result.created_batch_ids.append(new_batch_id)
                    result.created_platforms.append(platform)

                if result.created_batch_ids:
                    db.execute(
                        "UPDATE news_groups SET status='approved',updated_at=? WHERE id=?",
                        (requested_at, group_id),
                    )
                    db.execute(
                        "UPDATE articles SET status='approved' WHERE group_id=?",
                        (group_id,),
                    )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return result


__all__ = ["Database"]
