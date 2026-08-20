from __future__ import annotations

from .database import Database, LeaseLost, _iso
from .security import redact_secrets


class DatabaseV131RC1(Database):
    """RC1 queue-safety operations layered over the stable schema-8 database."""

    def recover_abandoned_batches(self, max_automatic_attempts: int = 3) -> list[int]:
        """Fail closed on packages left in_progress by a previous process."""
        limit = max(1, int(max_automatic_attempts))
        now = _iso()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                rows = db.execute(
                    "SELECT id FROM publication_batches WHERE status='in_progress' OR (status='pending' AND attempts>=?)",
                    (limit,),
                ).fetchall()
                ids = [int(row["id"]) for row in rows]
                if ids:
                    placeholders = ",".join("?" for _ in ids)
                    db.execute(
                        f"UPDATE publication_batches SET status='paused',lease_owner=NULL,lease_until=NULL,updated_at=? "
                        f"WHERE id IN ({placeholders})",
                        [now, *ids],
                    )
                    db.execute(
                        f"UPDATE publication_targets SET last_error=COALESCE(last_error, ?),updated_at=? "
                        f"WHERE batch_id IN ({placeholders}) AND status!='sent'",
                        [
                            "Попередню публікацію перервано або вичерпано ліміт автоматичних спроб. Перевірте платформи перед ручним відновленням.",
                            now,
                            *ids,
                        ],
                    )
                db.execute("COMMIT")
                return ids
            except Exception:
                db.execute("ROLLBACK")
                raise

    def pause_exhausted_batches(self, max_automatic_attempts: int = 3) -> list[int]:
        limit = max(1, int(max_automatic_attempts))
        now = _iso()
        with self.connect() as db:
            rows = db.execute(
                "SELECT id FROM publication_batches WHERE status='pending' AND attempts>=?",
                (limit,),
            ).fetchall()
            ids = [int(row["id"]) for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                db.execute(
                    f"UPDATE publication_batches SET status='paused',lease_owner=NULL,lease_until=NULL,updated_at=? "
                    f"WHERE id IN ({placeholders})",
                    [now, *ids],
                )
        return ids

    def mark_unsent_targets_failed(self, batch_id: int, error: object) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE publication_targets SET status='failed',last_error=?,updated_at=? "
                "WHERE batch_id=? AND status!='sent'",
                (redact_secrets(error)[:1000], _iso(), int(batch_id)),
            )

    def cancel_claimed_batch(self, batch_id: int, owner: str) -> None:
        """Cancel a batch only while the caller still owns its publication lease."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT a.group_id FROM publication_batches b JOIN articles a ON a.id=b.article_id "
                    "WHERE b.id=? AND b.status='in_progress' AND b.lease_owner=?",
                    (int(batch_id), owner),
                ).fetchone()
                if not row:
                    raise LeaseLost("Publication lease was lost before cancellation.")
                group_id = int(row["group_id"])
                now = _iso()
                db.execute(
                    "UPDATE publication_batches SET status='cancelled',lease_owner=NULL,lease_until=NULL,"
                    "cleanup_error=NULL,updated_at=? WHERE id=? AND lease_owner=?",
                    (now, int(batch_id), owner),
                )
                sent_count = int(
                    db.execute(
                        "SELECT COUNT(*) FROM publication_targets WHERE batch_id=? AND status='sent'",
                        (int(batch_id),),
                    ).fetchone()[0]
                    or 0
                )
                next_status = "approved" if sent_count else "draft"
                db.execute("UPDATE news_groups SET status=?,updated_at=? WHERE id=?", (next_status, now, group_id))
                db.execute("UPDATE articles SET status=? WHERE group_id=?", (next_status, group_id))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

    def fail_claimed_batch(
        self,
        batch_id: int,
        owner: str,
        error: object,
        *,
        max_automatic_attempts: int = 3,
    ) -> None:
        """Apply bounded retry/backoff to failures outside the target loop."""
        self.assert_lease(batch_id, owner)
        self.mark_unsent_targets_failed(batch_id, error)
        self.finish_batch(
            batch_id,
            owner,
            max_automatic_attempts=max_automatic_attempts,
        )
