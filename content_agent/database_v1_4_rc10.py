from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable

from .database import _iso
from .database_v1_4_rc9 import Database as Rc9Database


_IMMEDIATE_PRIORITY_AT = "2000-01-01T00:00:00+00:00"
_IMMEDIATE_MARKER = '"publish_now": true'
_ACTIVE_STATUSES = {"pending", "in_progress", "paused"}


@dataclass(slots=True)
class ImmediatePublishResult:
    batch_ids: dict[str, int] = field(default_factory=dict)
    created: list[str] = field(default_factory=list)
    blocked_active: list[str] = field(default_factory=list)
    already_final: list[str] = field(default_factory=list)
    requested_at: str = ""


class Database(Rc9Database):
    """RC10 immediate-publication path that never consumes normal schedule slots."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._repair_terminal_immediate_timestamps()

    @staticmethod
    def _is_immediate_progress(raw: object) -> bool:
        try:
            payload = json.loads(str(raw or "{}"))
        except json.JSONDecodeError:
            return False
        return isinstance(payload, dict) and payload.get("publish_now") is True

    def immediate_batch_ids(self, batch_ids: Iterable[int]) -> set[int]:
        ids = sorted({int(value) for value in batch_ids if int(value) > 0})
        if not ids:
            return set()
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT DISTINCT batch_id
                FROM publication_targets
                WHERE batch_id IN ({placeholders})
                  AND progress_json LIKE ?
                """,
                [*ids, f"%{_IMMEDIATE_MARKER}%"],
            ).fetchall()
        return {int(row[0]) for row in rows}

    def is_immediate_batch(self, batch_id: int) -> bool:
        return int(batch_id) in self.immediate_batch_ids([batch_id])

    def has_pending_immediate(self) -> bool:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT 1
                FROM publication_batches b
                JOIN publication_targets t ON t.batch_id=b.id
                WHERE b.status='pending'
                  AND t.status='pending'
                  AND t.progress_json LIKE ?
                LIMIT 1
                """,
                (f"%{_IMMEDIATE_MARKER}%",),
            ).fetchone()
        return row is not None

    def list_batches(self, *args, **kwargs):
        rows = super().list_batches(*args, **kwargs)
        statuses = kwargs.get("statuses")
        if statuses is None:
            return rows
        normalized = {str(value) for value in statuses}
        if not normalized or not normalized.issubset(_ACTIVE_STATUSES):
            return rows
        hidden = self.immediate_batch_ids(batch.id for batch in rows)
        return [batch for batch in rows if int(batch.id) not in hidden]

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
            WHERE t.platform=?
              AND b.status!='cancelled'
              AND t.progress_json NOT LIKE ?
        """
        params: list[object] = [str(platform), f"%{_IMMEDIATE_MARKER}%"]
        if exclude_group_id is not None:
            query += " AND a.group_id!=?"
            params.append(int(exclude_group_id))
        query += " ORDER BY julianday(b.scheduled_at) DESC,b.id DESC LIMIT 1"
        with self.connect() as db:
            row = db.execute(query, params).fetchone()
        return str(row[0]) if row and row[0] else None

    def scheduled_times_for_target(self, platform: str, *, active_only: bool = True) -> list[str]:
        query = """
            SELECT b.scheduled_at
            FROM publication_batches b
            JOIN publication_targets t ON t.batch_id=b.id
            WHERE t.platform=?
              AND b.status!='cancelled'
              AND t.progress_json NOT LIKE ?
        """
        params: list[object] = [str(platform), f"%{_IMMEDIATE_MARKER}%"]
        if active_only:
            query += " AND b.status IN ('pending','in_progress','paused')"
        query += " ORDER BY julianday(b.scheduled_at),b.id"
        with self.connect() as db:
            return [str(row[0]) for row in db.execute(query, params).fetchall() if row[0]]

    def create_immediate_targets(
        self,
        article_id: int,
        targets: dict[str, str],
        *,
        display_title: str,
    ) -> ImmediatePublishResult:
        if not targets:
            raise ValueError("Оберіть хоча б один профіль, сторінку або канал.")
        cleaned = {str(key).strip(): str(value).strip() for key, value in targets.items()}
        if any(not key or not value for key, value in cleaned.items()):
            raise ValueError("Кожна ціль публікації повинна мати непорожній текст.")

        group_id = self.group_id_for_article(int(article_id))
        title = " ".join(str(display_title or "").split()).strip()[:300]
        requested_at = _iso()
        result = ImmediatePublishResult(requested_at=requested_at)
        archived_final = self._archived_final_for_group(group_id)

        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                active_rows = db.execute(
                    """
                    SELECT DISTINCT t.platform
                    FROM publication_targets t
                    JOIN publication_batches b ON b.id=t.batch_id
                    JOIN articles a ON a.id=b.article_id
                    WHERE a.group_id=?
                      AND b.status IN ('pending','in_progress','paused')
                      AND t.status='pending'
                    """,
                    (group_id,),
                ).fetchall()
                active = {str(row[0]) for row in active_rows}

                final_rows = db.execute(
                    """
                    SELECT DISTINCT t.platform
                    FROM publication_targets t
                    JOIN publication_batches b ON b.id=t.batch_id
                    JOIN articles a ON a.id=b.article_id
                    WHERE a.group_id=?
                      AND b.status!='cancelled'
                      AND t.status IN ('sent','failed')
                    """,
                    (group_id,),
                ).fetchall()
                final = {str(row[0]) for row in final_rows} | archived_final

                for platform, text in cleaned.items():
                    if platform in active:
                        result.blocked_active.append(platform)
                        continue
                    if platform in final:
                        result.already_final.append(platform)
                        continue

                    progress = {
                        "display_title": title,
                        "publish_now": True,
                        "publish_now_requested_at": requested_at,
                    }
                    now = _iso()
                    cursor = db.execute(
                        """
                        INSERT INTO publication_batches(
                            article_id,scheduled_at,status,lease_owner,lease_until,attempts,
                            cleanup_error,created_at,updated_at
                        ) VALUES(?,?,'pending',NULL,NULL,0,NULL,?,?)
                        """,
                        (int(article_id), _IMMEDIATE_PRIORITY_AT, now, now),
                    )
                    batch_id = int(cursor.lastrowid)
                    db.execute(
                        """
                        INSERT INTO publication_targets(
                            batch_id,platform,payload_text,status,remote_id,last_error,progress_json,updated_at
                        ) VALUES(?,?,?,'pending',NULL,NULL,?,?)
                        """,
                        (
                            batch_id,
                            platform,
                            text,
                            json.dumps(progress, ensure_ascii=False, sort_keys=True),
                            now,
                        ),
                    )
                    result.batch_ids[platform] = batch_id
                    result.created.append(platform)

                if result.created:
                    now = _iso()
                    db.execute(
                        "UPDATE news_groups SET status='approved',updated_at=? WHERE id=?",
                        (now, group_id),
                    )
                    db.execute("UPDATE articles SET status='approved' WHERE group_id=?", (group_id,))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

        result.created = sorted(set(result.created))
        result.blocked_active = sorted(set(result.blocked_active))
        result.already_final = sorted(set(result.already_final))
        return result

    def finalize_immediate_timestamp(self, batch_id: int) -> bool:
        with self.connect() as db:
            row = db.execute(
                "SELECT progress_json FROM publication_targets WHERE batch_id=? ORDER BY id LIMIT 1",
                (int(batch_id),),
            ).fetchone()
            if row is None:
                return False
            try:
                progress = json.loads(str(row[0] or "{}"))
            except json.JSONDecodeError:
                return False
            if not isinstance(progress, dict) or progress.get("publish_now") is not True:
                return False
            requested = str(progress.get("publish_now_requested_at") or "").strip()
            if not requested:
                return False
            db.execute(
                "UPDATE publication_batches SET scheduled_at=?,updated_at=? WHERE id=?",
                (requested, _iso(), int(batch_id)),
            )
        return True

    def _repair_terminal_immediate_timestamps(self) -> int:
        repaired = 0
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT b.id,t.progress_json
                FROM publication_batches b
                JOIN publication_targets t ON t.batch_id=b.id
                WHERE b.status IN ('completed','cancelled')
                  AND t.progress_json LIKE ?
                """,
                (f"%{_IMMEDIATE_MARKER}%",),
            ).fetchall()
            for row in rows:
                try:
                    progress = json.loads(str(row["progress_json"] or "{}"))
                except json.JSONDecodeError:
                    continue
                requested = str(progress.get("publish_now_requested_at") or "").strip() if isinstance(progress, dict) else ""
                if not requested:
                    continue
                db.execute(
                    "UPDATE publication_batches SET scheduled_at=? WHERE id=?",
                    (requested, int(row["id"])),
                )
                repaired += 1
        return repaired
