from __future__ import annotations

from typing import Iterable

from .database_v1_4 import Database as V14Database
from .database import _iso


class Database(V14Database):
    """Final v1.4 runtime guards layered over the destination queue model."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._terminalize_legacy_paused_batches()

    def _terminalize_legacy_paused_batches(self) -> int:
        """Old paused failures must not become a hidden retry queue in v1.4."""
        message = (
            "Завдання було призупинене старою версією. У v1.4 автоматичні повтори вимкнено; "
            "запис перенесено в історію як завершений з помилкою."
        )
        with self.connect() as db:
            rows = db.execute("SELECT id FROM publication_batches WHERE status='paused'").fetchall()
            ids = [int(row[0]) for row in rows]
            if not ids:
                return 0
            placeholders = ",".join("?" for _ in ids)
            now = _iso()
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    f"""
                    UPDATE publication_targets
                    SET status=CASE WHEN status='sent' THEN 'sent' ELSE 'failed' END,
                        last_error=CASE WHEN status='sent' THEN last_error ELSE COALESCE(last_error,?) END,
                        updated_at=?
                    WHERE batch_id IN ({placeholders})
                    """,
                    [message, now, *ids],
                )
                db.execute(
                    f"""
                    UPDATE publication_batches
                    SET status='completed',lease_owner=NULL,lease_until=NULL,updated_at=?
                    WHERE id IN ({placeholders})
                    """,
                    [now, *ids],
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return len(ids)

    def _reconcile_group_publication_state(self, group_ids: Iterable[int]) -> None:
        ids = sorted({int(value) for value in group_ids if int(value) > 0})
        if not ids:
            return
        now = _iso()
        with self.connect() as db:
            for group_id in ids:
                active = int(
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
                final = int(
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
                archived = bool(self._archived_final_for_group(group_id))
                status = "approved" if active or final or archived else "draft"
                db.execute("UPDATE news_groups SET status=?,updated_at=? WHERE id=?", (status, now, group_id))
                db.execute("UPDATE articles SET status=? WHERE group_id=?", (status, group_id))

    def cancel_batches(self, batch_ids: Iterable[int]) -> list[int]:
        requested = [int(value) for value in batch_ids]
        group_ids: list[int] = []
        for batch_id in requested:
            try:
                group_ids.append(self.group_id_for_batch(batch_id))
            except KeyError:
                pass
        cancelled = super().cancel_batches(requested)
        self._reconcile_group_publication_state(group_ids)
        return cancelled

    def cancel_claimed_batch(self, batch_id: int, owner: str) -> None:
        try:
            group_id = self.group_id_for_batch(batch_id)
        except KeyError:
            group_id = 0
        super().cancel_claimed_batch(batch_id, owner)
        if group_id:
            self._reconcile_group_publication_state([group_id])
