from __future__ import annotations

from collections.abc import Callable
from sqlite3 import Connection

from ...database import _iso
from ..publishing.outcomes import derive_outcome

Migration = tuple[str, Callable[[Connection], None]]


def _columns(db: Connection, table: str) -> set[str]:
    return {str(row[1]) for row in db.execute(f"PRAGMA table_info({table})").fetchall()}


def _migration_0009_publication_target_outcome(db: Connection) -> None:
    if "outcome" not in _columns(db, "publication_targets"):
        db.execute(
            "ALTER TABLE publication_targets "
            "ADD COLUMN outcome TEXT NOT NULL DEFAULT 'not_attempted'"
        )
    rows = db.execute(
        "SELECT id,status,remote_id,last_error,progress_json,outcome FROM publication_targets"
    ).fetchall()
    for row in rows:
        outcome = derive_outcome(
            status=row["status"],
            remote_id=row["remote_id"],
            last_error=row["last_error"],
            progress_json=row["progress_json"],
            current=row["outcome"],
        )
        db.execute(
            "UPDATE publication_targets SET outcome=? WHERE id=?",
            (outcome.value, int(row["id"])),
        )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_publication_targets_outcome "
        "ON publication_targets(outcome,status,batch_id)"
    )


MIGRATIONS: tuple[Migration, ...] = (
    ("0009_publication_target_outcome", _migration_0009_publication_target_outcome),
)


def apply_v2_migrations(database: object) -> tuple[str, ...]:
    """Apply additive V2 migrations after the legacy R8 schema is initialized.

    `PRAGMA user_version=8` remains the compatibility baseline for the historical
    database. New V2 changes are tracked explicitly here so constructors no longer
    need to become the source of truth for every future schema addition.
    """

    applied_now: list[str] = []
    with database.connect() as db:  # type: ignore[attr-defined]
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {
                str(row[0])
                for row in db.execute("SELECT id FROM schema_migrations").fetchall()
            }
            for migration_id, function in MIGRATIONS:
                if migration_id in applied:
                    continue
                function(db)
                db.execute(
                    "INSERT INTO schema_migrations(id,applied_at) VALUES(?,?)",
                    (migration_id, _iso()),
                )
                applied_now.append(migration_id)
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
    return tuple(applied_now)


__all__ = ["MIGRATIONS", "apply_v2_migrations"]
