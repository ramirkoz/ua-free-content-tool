from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Iterable

from .database import LeaseLost, _iso, _normalize_scheduled_at, _now, _parse_aware_iso
from .database_rc14 import Database as Rc14Database, PUBLICATION_HISTORY_RETENTION_DAYS
from .security import redact_secrets


@dataclass(slots=True)
class IndependentQueueResult:
    batch_ids: dict[str, int] = field(default_factory=dict)
    scheduled_at: dict[str, str] = field(default_factory=dict)
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    already_final: list[str] = field(default_factory=list)


class Database(Rc14Database):
    """v1.4 publication model: one independent queue batch per destination."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._migrate_active_multi_target_batches_v14()

    # ------------------------------------------------------------------
    # One active batch per concrete destination.
    # ------------------------------------------------------------------
    def _migrate_active_multi_target_batches_v14(self) -> int:
        """Split old multi-target active packages without replaying failed targets.

        Completed/cancelled history remains untouched. A pending target becomes its
        own pending package. A target that was already sent or failed becomes a
        completed historical package. The old container package is cancelled.
        """
        migrated = 0
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT b.*,(SELECT COUNT(*) FROM publication_targets t WHERE t.batch_id=b.id) AS target_count
                FROM publication_batches b
                WHERE b.status IN ('pending','paused')
                  AND (SELECT COUNT(*) FROM publication_targets t WHERE t.batch_id=b.id)>1
                ORDER BY b.id
                """
            ).fetchall()
            if not rows:
                return 0
            db.execute("BEGIN IMMEDIATE")
            try:
                now = _iso()
                for batch in rows:
                    batch_id = int(batch["id"])
                    targets = db.execute(
                        "SELECT * FROM publication_targets WHERE batch_id=? ORDER BY id",
                        (batch_id,),
                    ).fetchall()
                    for target in targets:
                        target_status = str(target["status"])
                        new_status = "pending" if target_status == "pending" else "completed"
                        cursor = db.execute(
                            """
                            INSERT INTO publication_batches(
                                article_id,scheduled_at,status,lease_owner,lease_until,attempts,
                                cleanup_error,created_at,updated_at
                            ) VALUES(?,?,?,NULL,NULL,0,NULL,?,?)
                            """,
                            (
                                int(batch["article_id"]),
                                str(batch["scheduled_at"]),
                                new_status,
                                str(batch["created_at"] or now),
                                now,
                            ),
                        )
                        new_batch_id = int(cursor.lastrowid)
                        db.execute(
                            "UPDATE publication_targets SET batch_id=?,updated_at=? WHERE id=?",
                            (new_batch_id, now, int(target["id"])),
                        )
                    db.execute(
                        """
                        UPDATE publication_batches
                        SET status='cancelled',lease_owner=NULL,lease_until=NULL,cleanup_error=NULL,updated_at=?
                        WHERE id=?
                        """,
                        (now, batch_id),
                    )
                    migrated += 1
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return migrated

    def latest_scheduled_for_target(
        self,
        platform: str,
        *,
        exclude_group_id: int | None = None,
    ) -> str | None:
        query = """
            SELECT b.scheduled_at
            FROM publication_batches b
            JOIN publication_targets t ON t.batch_id=b.id
            JOIN articles a ON a.id=b.article_id
            WHERE t.platform=? AND b.status!='cancelled'
        """
        params: list[object] = [str(platform)]
        if exclude_group_id is not None:
            query += " AND a.group_id!=?"
            params.append(int(exclude_group_id))
        query += " ORDER BY julianday(b.scheduled_at) DESC,b.id DESC LIMIT 1"
        with self.connect() as db:
            row = db.execute(query, params).fetchone()
        return str(row[0]) if row and row[0] else None

    def scheduled_times_for_target(self, platform: str, *, active_only: bool = True) -> list[str]:
        query = """
            SELECT b.scheduled_at FROM publication_batches b
            JOIN publication_targets t ON t.batch_id=b.id
            WHERE t.platform=? AND b.status!='cancelled'
        """
        params: list[object] = [str(platform)]
        if active_only:
            query += " AND b.status IN ('pending','in_progress','paused')"
        query += " ORDER BY julianday(b.scheduled_at),b.id"
        with self.connect() as db:
            return [str(row[0]) for row in db.execute(query, params).fetchall() if row[0]]

    def _archived_final_for_group(self, group_id: int) -> set[str]:
        with self.connect() as db:
            self._ensure_publication_archive(db)
            rows = db.execute(
                """
                SELECT DISTINCT t.platform
                FROM archived_publication_targets t
                JOIN archived_publication_batches b ON b.batch_id=t.batch_id
                WHERE b.group_id=? AND t.status IN ('sent','failed')
                """,
                (int(group_id),),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def queue_independent_targets(
        self,
        article_id: int,
        targets: dict[str, str],
        schedules: dict[str, str],
        *,
        display_title: str,
    ) -> IndependentQueueResult:
        if not targets:
            raise ValueError("Оберіть хоча б один профіль, сторінку або канал.")
        cleaned = {str(key).strip(): str(value).strip() for key, value in targets.items()}
        if any(not key or not value for key, value in cleaned.items()):
            raise ValueError("Кожна ціль публікації повинна мати непорожній текст.")
        normalized_schedules = {
            key: _normalize_scheduled_at(str(schedules[key]))
            for key in cleaned
            if key in schedules
        }
        if set(normalized_schedules) != set(cleaned):
            raise ValueError("Для кожної цілі потрібен окремий час публікації.")

        group_id = self.group_id_for_article(article_id)
        title = " ".join(str(display_title or "").split()).strip()[:300]
        result = IndependentQueueResult()
        archived_final = self._archived_final_for_group(group_id)

        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                now = _iso()
                requested = set(cleaned)

                active_rows = db.execute(
                    """
                    SELECT b.id AS batch_id,b.status AS batch_status,b.scheduled_at,
                           t.id AS target_id,t.platform,t.status AS target_status,t.progress_json
                    FROM publication_batches b
                    JOIN articles a ON a.id=b.article_id
                    JOIN publication_targets t ON t.batch_id=b.id
                    WHERE a.group_id=? AND b.status IN ('pending','paused')
                    ORDER BY b.id,t.id
                    """,
                    (group_id,),
                ).fetchall()

                # Removing a checkbox cancels only that unsent destination. Other
                # destination queues for the same story are completely untouched.
                for row in active_rows:
                    platform = str(row["platform"])
                    if platform in requested:
                        continue
                    db.execute(
                        "UPDATE publication_batches SET status='cancelled',lease_owner=NULL,lease_until=NULL,updated_at=? WHERE id=?",
                        (now, int(row["batch_id"])),
                    )
                    result.removed.append(platform)

                live_final = {
                    str(row["platform"])
                    for row in db.execute(
                        """
                        SELECT DISTINCT t.platform
                        FROM publication_targets t
                        JOIN publication_batches b ON b.id=t.batch_id
                        JOIN articles a ON a.id=b.article_id
                        WHERE a.group_id=? AND b.status!='cancelled' AND t.status IN ('sent','failed')
                        """,
                        (group_id,),
                    ).fetchall()
                }
                final_platforms = live_final | archived_final

                for platform, text in cleaned.items():
                    if platform in final_platforms:
                        result.already_final.append(platform)
                        continue

                    existing = db.execute(
                        """
                        SELECT b.id AS batch_id,b.status AS batch_status,b.scheduled_at,
                               t.id AS target_id,t.status AS target_status,t.progress_json
                        FROM publication_batches b
                        JOIN articles a ON a.id=b.article_id
                        JOIN publication_targets t ON t.batch_id=b.id
                        WHERE a.group_id=? AND t.platform=? AND b.status IN ('pending','paused')
                        ORDER BY b.id DESC LIMIT 1
                        """,
                        (group_id, platform),
                    ).fetchone()

                    progress: dict[str, object] = {"display_title": title}
                    schedule = normalized_schedules[platform]
                    if existing is not None:
                        try:
                            old_progress = json.loads(str(existing["progress_json"] or "{}"))
                        except json.JSONDecodeError:
                            old_progress = {}
                        if isinstance(old_progress, dict):
                            progress = {**old_progress, "display_title": title}
                        current_schedule = str(existing["scheduled_at"])
                        try:
                            if _parse_aware_iso(current_schedule) > _now():
                                schedule = current_schedule
                        except ValueError:
                            pass
                        db.execute(
                            """
                            UPDATE publication_targets
                            SET payload_text=?,status='pending',remote_id=NULL,last_error=NULL,
                                progress_json=?,updated_at=? WHERE id=?
                            """,
                            (
                                text,
                                json.dumps(progress, ensure_ascii=False, sort_keys=True),
                                now,
                                int(existing["target_id"]),
                            ),
                        )
                        db.execute(
                            """
                            UPDATE publication_batches
                            SET status='pending',scheduled_at=?,lease_owner=NULL,lease_until=NULL,
                                attempts=0,cleanup_error=NULL,updated_at=? WHERE id=?
                            """,
                            (schedule, now, int(existing["batch_id"])),
                        )
                        batch_id = int(existing["batch_id"])
                        result.updated.append(platform)
                    else:
                        cursor = db.execute(
                            """
                            INSERT INTO publication_batches(article_id,scheduled_at,status,created_at,updated_at)
                            VALUES(?,?,'pending',?,?)
                            """,
                            (article_id, schedule, now, now),
                        )
                        batch_id = int(cursor.lastrowid)
                        db.execute(
                            """
                            INSERT INTO publication_targets(
                                batch_id,platform,payload_text,status,progress_json,updated_at
                            ) VALUES(?,?,?,'pending',?,?)
                            """,
                            (
                                batch_id,
                                platform,
                                text,
                                json.dumps(progress, ensure_ascii=False, sort_keys=True),
                                now,
                            ),
                        )
                        result.added.append(platform)

                    result.batch_ids[platform] = batch_id
                    result.scheduled_at[platform] = schedule

                remaining = int(
                    db.execute(
                        """
                        SELECT COUNT(*) FROM publication_batches b
                        JOIN articles a ON a.id=b.article_id
                        WHERE a.group_id=? AND b.status IN ('pending','in_progress','paused')
                        """,
                        (group_id,),
                    ).fetchone()[0]
                    or 0
                )
                finalized = int(
                    db.execute(
                        """
                        SELECT COUNT(*) FROM publication_targets t
                        JOIN publication_batches b ON b.id=t.batch_id
                        JOIN articles a ON a.id=b.article_id
                        WHERE a.group_id=? AND b.status!='cancelled' AND t.status IN ('sent','failed')
                        """,
                        (group_id,),
                    ).fetchone()[0]
                    or 0
                )
                next_status = "approved" if remaining or finalized or archived_final else "draft"
                db.execute("UPDATE news_groups SET status=?,updated_at=? WHERE id=?", (next_status, now, group_id))
                db.execute("UPDATE articles SET status=? WHERE group_id=?", (next_status, group_id))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        result.already_final = sorted(set(result.already_final))
        result.removed = sorted(set(result.removed))
        return result

    # ------------------------------------------------------------------
    # Errors are terminal. A failed API attempt is history, never a retry.
    # ------------------------------------------------------------------
    def all_targets_terminal(self, batch_id: int) -> bool:
        with self.connect() as db:
            rows = db.execute(
                "SELECT status FROM publication_targets WHERE batch_id=?",
                (int(batch_id),),
            ).fetchall()
        return bool(rows) and all(str(row[0]) in {"sent", "failed"} for row in rows)

    def finish_batch(
        self,
        batch_id: int,
        owner: str,
        *,
        retry_minutes: int | None = None,
        pause: bool = False,
        max_automatic_attempts: int = 1,
    ) -> bool:
        del retry_minutes, pause, max_automatic_attempts
        self.assert_lease(batch_id, owner)
        terminal = self.all_targets_terminal(batch_id)
        if not terminal:
            # This can only happen when the user explicitly stopped a package before
            # a target attempt. Keep it paused rather than inventing a publication.
            with self.connect() as db:
                db.execute(
                    """
                    UPDATE publication_batches SET status='paused',lease_owner=NULL,lease_until=NULL,updated_at=?
                    WHERE id=? AND lease_owner=?
                    """,
                    (_iso(), int(batch_id), owner),
                )
            return False
        with self.connect() as db:
            db.execute(
                """
                UPDATE publication_batches SET status='completed',lease_owner=NULL,lease_until=NULL,
                    cleanup_error=NULL,updated_at=? WHERE id=? AND lease_owner=?
                """,
                (_iso(), int(batch_id), owner),
            )
        return True

    def fail_claimed_batch(
        self,
        batch_id: int,
        owner: str,
        error: object,
        *,
        max_automatic_attempts: int = 1,
    ) -> None:
        del max_automatic_attempts
        self.assert_lease(batch_id, owner)
        self.mark_unsent_targets_failed(batch_id, error)
        self.finish_batch(batch_id, owner)

    def defer_cleanup(
        self,
        batch_id: int,
        owner: str,
        error: object,
        retry_minutes: int = 15,
        *,
        max_automatic_attempts: int = 1,
    ) -> None:
        del retry_minutes, max_automatic_attempts
        self.assert_lease(batch_id, owner)
        with self.connect() as db:
            db.execute(
                """
                UPDATE publication_batches SET status='completed',lease_owner=NULL,lease_until=NULL,
                    cleanup_error=?,updated_at=? WHERE id=? AND lease_owner=?
                """,
                (redact_secrets(error)[:1000], _iso(), int(batch_id), owner),
            )

    def recover_abandoned_batches(self, max_automatic_attempts: int = 1) -> list[int]:
        del max_automatic_attempts
        if getattr(self, "_rc14_defer_startup_maintenance", False):
            return []
        message = (
            "Попередню спробу публікації було перервано. Результат невідомий; "
            "автоматичний повтор вимкнено, щоб не створити дубль."
        )
        with self.connect() as db:
            rows = db.execute("SELECT id FROM publication_batches WHERE status='in_progress'").fetchall()
            ids = [int(row[0]) for row in rows]
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            now = _iso()
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    f"UPDATE publication_targets SET status='failed',last_error=COALESCE(last_error,?),updated_at=? "
                    f"WHERE batch_id IN ({placeholders}) AND status!='sent'",
                    [message, now, *ids],
                )
                db.execute(
                    f"UPDATE publication_batches SET status='completed',lease_owner=NULL,lease_until=NULL,updated_at=? "
                    f"WHERE id IN ({placeholders})",
                    [now, *ids],
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return ids

    def pause_exhausted_batches(self, max_automatic_attempts: int = 1) -> list[int]:
        limit = max(1, int(max_automatic_attempts))
        with self.connect() as db:
            rows = db.execute(
                "SELECT id FROM publication_batches WHERE status='pending' AND attempts>=?",
                (limit,),
            ).fetchall()
            ids = [int(row[0]) for row in rows]
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            now = _iso()
            error = "Ліміт спроб вичерпано. Автоматичний повтор вимкнено; запис перенесено в історію."
            db.execute(
                f"UPDATE publication_targets SET status='failed',last_error=COALESCE(last_error,?),updated_at=? "
                f"WHERE batch_id IN ({placeholders}) AND status!='sent'",
                [error, now, *ids],
            )
            db.execute(
                f"UPDATE publication_batches SET status='completed',lease_owner=NULL,lease_until=NULL,updated_at=? "
                f"WHERE id IN ({placeholders})",
                [now, *ids],
            )
        return ids

    # ------------------------------------------------------------------
    # Shared media lives until every destination for the story is terminal.
    # ------------------------------------------------------------------
    def media_cleanup_ready_for_group(self, group_id: int) -> bool:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT COUNT(*)
                FROM publication_batches b
                JOIN articles a ON a.id=b.article_id
                JOIN publication_targets t ON t.batch_id=b.id
                WHERE a.group_id=? AND b.status IN ('pending','in_progress','paused')
                  AND t.status NOT IN ('sent','failed')
                """,
                (int(group_id),),
            ).fetchone()
        return int(row[0] or 0) == 0

    def clear_group_media(self, group_id: int) -> None:
        if not self.media_cleanup_ready_for_group(group_id):
            return
        super().clear_group_media(group_id)

    # ------------------------------------------------------------------
    # History includes sent AND terminal errors, with a stable editor title.
    # ------------------------------------------------------------------
    def list_publication_history(
        self,
        limit: int = 500,
        *,
        retention_days: int = PUBLICATION_HISTORY_RETENTION_DAYS,
    ) -> list[dict[str, object]]:
        cutoff = _iso(_now() - timedelta(days=max(1, int(retention_days))))
        with self.connect() as db:
            rows = db.execute(
                """
                WITH recent AS (
                    SELECT DISTINCT b.id
                    FROM publication_batches b
                    JOIN publication_targets x ON x.batch_id=b.id
                    WHERE b.status='completed'
                      AND x.status IN ('sent','failed')
                      AND julianday(COALESCE((
                          SELECT MAX(z.updated_at) FROM publication_targets z
                          WHERE z.batch_id=b.id AND z.status IN ('sent','failed')
                      ),b.updated_at,b.scheduled_at))>=julianday(?)
                    ORDER BY b.id DESC LIMIT ?
                )
                SELECT b.id AS batch_id,b.scheduled_at,b.status AS batch_status,
                       a.group_id,g.headline,g.rewrite_text,
                       t.id AS target_id,t.platform,t.status AS target_status,t.remote_id,
                       t.last_error,t.progress_json,t.updated_at
                FROM recent r
                JOIN publication_batches b ON b.id=r.id
                JOIN articles a ON a.id=b.article_id
                JOIN news_groups g ON g.id=a.group_id
                JOIN publication_targets t ON t.batch_id=b.id
                ORDER BY b.id DESC,t.id
                """,
                (cutoff, max(1, int(limit))),
            ).fetchall()

        grouped: dict[int, dict[str, object]] = {}
        for row in rows:
            try:
                progress = json.loads(str(row["progress_json"] or "{}"))
            except json.JSONDecodeError:
                progress = {}
            if not isinstance(progress, dict):
                progress = {}
            display_title = str(progress.get("display_title") or "").strip()
            if not display_title:
                display_title = str(row["headline"] or "").strip()
            if not display_title:
                paragraphs = [" ".join(part.split()) for part in str(row["rewrite_text"] or "").split("\n\n")]
                display_title = next((part for part in paragraphs if part), "Матеріал без редакційного заголовка")
                if len(display_title) > 140:
                    display_title = display_title[:139].rstrip(" ,.;:-") + "…"

            batch_id = int(row["batch_id"])
            item = grouped.setdefault(
                batch_id,
                {
                    "batch_id": batch_id,
                    "group_id": int(row["group_id"]),
                    "headline": display_title,
                    "display_title": display_title,
                    "rewrite_text": str(row["rewrite_text"] or ""),
                    "scheduled_at": str(row["scheduled_at"] or ""),
                    "batch_status": str(row["batch_status"] or ""),
                    "published_at": "",
                    "targets": [],
                },
            )
            target = {
                "id": int(row["target_id"]),
                "platform": str(row["platform"]),
                "status": str(row["target_status"]),
                "remote_id": str(row["remote_id"] or ""),
                "last_error": str(row["last_error"] or ""),
                "updated_at": str(row["updated_at"] or ""),
                "progress": progress,
            }
            item["targets"].append(target)  # type: ignore[union-attr]
            terminal_at = str(target["updated_at"] or "")
            if terminal_at > str(item["published_at"]):
                item["published_at"] = terminal_at
        return list(grouped.values())[: max(1, int(limit))]

    def archive_old_publication_history(
        self,
        retention_days: int = PUBLICATION_HISTORY_RETENTION_DAYS,
        *,
        limit: int = 5000,
    ) -> int:
        """Archive both successful and terminal-error publication jobs."""
        days = max(1, int(retention_days))
        cutoff = _iso(_now() - timedelta(days=days))
        with self.connect() as db:
            self._ensure_publication_archive(db)
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("CREATE TEMP TABLE IF NOT EXISTS v14_archive_ids(id INTEGER PRIMARY KEY)")
                db.execute("DELETE FROM v14_archive_ids")
                db.execute(
                    """
                    INSERT INTO v14_archive_ids(id)
                    SELECT b.id FROM publication_batches b
                    WHERE b.status IN ('completed','cancelled')
                      AND EXISTS (SELECT 1 FROM publication_targets t WHERE t.batch_id=b.id AND t.status IN ('sent','failed'))
                      AND julianday(COALESCE((SELECT MAX(t.updated_at) FROM publication_targets t
                          WHERE t.batch_id=b.id AND t.status IN ('sent','failed')),b.updated_at,b.scheduled_at))<julianday(?)
                    ORDER BY b.id LIMIT ?
                    """,
                    (cutoff, max(1, int(limit))),
                )
                count = int(db.execute("SELECT COUNT(*) FROM v14_archive_ids").fetchone()[0] or 0)
                if not count:
                    db.execute("COMMIT")
                    return 0
                archived_at = _iso()
                db.execute(
                    """
                    INSERT OR REPLACE INTO archived_publication_batches(
                        batch_id,article_id,group_id,scheduled_at,batch_status,headline,
                        canonical_title,rewrite_text,published_at,archived_at
                    )
                    SELECT b.id,b.article_id,a.group_id,b.scheduled_at,b.status,g.headline,
                           g.canonical_title,g.rewrite_text,
                           COALESCE((SELECT MAX(t.updated_at) FROM publication_targets t
                           WHERE t.batch_id=b.id AND t.status IN ('sent','failed')),b.updated_at),?
                    FROM publication_batches b
                    JOIN articles a ON a.id=b.article_id
                    JOIN news_groups g ON g.id=a.group_id
                    WHERE b.id IN (SELECT id FROM v14_archive_ids)
                    """,
                    (archived_at,),
                )
                db.execute(
                    """
                    INSERT OR REPLACE INTO archived_publication_targets(
                        target_id,batch_id,platform,payload_text,status,remote_id,last_error,progress_json,updated_at
                    )
                    SELECT t.id,t.batch_id,t.platform,t.payload_text,t.status,t.remote_id,t.last_error,t.progress_json,t.updated_at
                    FROM publication_targets t WHERE t.batch_id IN (SELECT id FROM v14_archive_ids)
                    """
                )
                db.execute("DELETE FROM publication_batches WHERE id IN (SELECT id FROM v14_archive_ids)")
                db.execute("DELETE FROM v14_archive_ids")
                db.execute("COMMIT")
                return count
            except Exception:
                db.execute("ROLLBACK")
                raise

    def group_labels_for_batches(self, batch_ids: Iterable[int]) -> dict[int, str]:
        ids = sorted({int(value) for value in batch_ids if int(value) > 0})
        if not ids:
            return {}
        result: dict[int, str] = {}
        with self.connect() as db:
            for start in range(0, len(ids), 400):
                chunk = ids[start:start + 400]
                placeholders = ",".join("?" for _ in chunk)
                rows = db.execute(
                    f"""
                    SELECT b.id AS batch_id,g.id AS group_id,g.headline,g.rewrite_text,
                           (SELECT t.progress_json FROM publication_targets t WHERE t.batch_id=b.id ORDER BY t.id LIMIT 1) AS progress_json
                    FROM publication_batches b
                    JOIN articles a ON a.id=b.article_id
                    JOIN news_groups g ON g.id=a.group_id
                    WHERE b.id IN ({placeholders})
                    """,
                    chunk,
                ).fetchall()
                for row in rows:
                    title = ""
                    try:
                        progress = json.loads(str(row["progress_json"] or "{}"))
                        if isinstance(progress, dict):
                            title = str(progress.get("display_title") or "").strip()
                    except json.JSONDecodeError:
                        pass
                    if not title:
                        title = str(row["headline"] or "").strip()
                    if not title:
                        paragraphs = [" ".join(part.split()) for part in str(row["rewrite_text"] or "").split("\n\n")]
                        title = next((part for part in paragraphs if part), f"Матеріал #{int(row['group_id'])}")
                    if len(title) > 140:
                        title = title[:139].rstrip(" ,.;:-") + "…"
                    result[int(row["batch_id"])] = title
        return result
