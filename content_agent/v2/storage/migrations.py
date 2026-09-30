from __future__ import annotations

from collections.abc import Callable
from sqlite3 import Connection

from ...database import _iso
from ..publishing.outcomes import derive_outcome

Migration = tuple[str, Callable[[Connection], None]]


def _columns(db: Connection, table: str) -> set[str]:
    return {str(row[1]) for row in db.execute(f"PRAGMA table_info({table})").fetchall()}


def _migration_0008_manual_topics(db: Connection) -> None:
    """Adopt the RC43 manual-topic schema into the numbered registry.

    Existing installations may already contain the table/column because RC43/RC44
    created them from a mixin constructor. The migration is deliberately idempotent
    so those installations are simply recorded as migrated.
    """

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS manual_topics(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    if "topic_id" not in _columns(db, "sources"):
        db.execute("ALTER TABLE sources ADD COLUMN topic_id INTEGER")
    db.execute("CREATE INDEX IF NOT EXISTS idx_sources_topic_id ON sources(topic_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_manual_topics_name ON manual_topics(name COLLATE NOCASE)")


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


def _migration_0010_articles_discovered_at_index(db: Connection) -> None:
    """Keep current-day counters off full-table scans on large portable databases."""
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_articles_discovered_at "
        "ON articles(discovered_at)"
    )


MIGRATIONS: tuple[Migration, ...] = (
    ("0008_manual_topics", _migration_0008_manual_topics),
    ("0009_publication_target_outcome", _migration_0009_publication_target_outcome),
    ("0010_articles_discovered_at_index", _migration_0010_articles_discovered_at_index),
)


def apply_v2_migrations(database: object) -> tuple[str, ...]:
    """Apply additive V2 migrations after the legacy R8 schema is initialized.

    `PRAGMA user_version=8` remains the compatibility baseline for the historical
    database. V2 schema changes are tracked explicitly here and must not be added
    to UI or mixin constructors.
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
