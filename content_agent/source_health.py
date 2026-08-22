from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .security import redact_secrets

UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class SourceHealth:
    source_id: int
    last_success_at: str = ""
    last_new_at: str = ""
    last_error_at: str = ""
    last_error: str = ""
    last_inserted_count: int = 0
    total_checks: int = 0
    total_errors: int = 0
    total_inserted: int = 0

    @property
    def state(self) -> str:
        if self.last_error_at and (not self.last_success_at or self.last_error_at >= self.last_success_at):
            return "🔴 помилка"
        if self.last_success_at:
            return "🟢 працює"
        return "— немає даних"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def ensure_source_health(database: object) -> None:
    with database.connect() as db:  # type: ignore[attr-defined]
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS source_health (
                source_id INTEGER PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
                last_success_at TEXT NOT NULL DEFAULT '',
                last_new_at TEXT NOT NULL DEFAULT '',
                last_error_at TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                last_inserted_count INTEGER NOT NULL DEFAULT 0,
                total_checks INTEGER NOT NULL DEFAULT 0,
                total_errors INTEGER NOT NULL DEFAULT 0,
                total_inserted INTEGER NOT NULL DEFAULT 0
            )
            """
        )


def record_source_success(database: object, source_id: int, inserted_count: int) -> None:
    ensure_source_health(database)
    now = _now()
    inserted = max(0, int(inserted_count))
    with database.connect() as db:  # type: ignore[attr-defined]
        db.execute(
            """
            INSERT INTO source_health(
                source_id,last_success_at,last_new_at,last_error_at,last_error,
                last_inserted_count,total_checks,total_errors,total_inserted
            ) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_id) DO UPDATE SET
                last_success_at=excluded.last_success_at,
                last_new_at=CASE WHEN excluded.last_inserted_count > 0 THEN excluded.last_success_at ELSE source_health.last_new_at END,
                last_error='',
                last_inserted_count=excluded.last_inserted_count,
                total_checks=source_health.total_checks + 1,
                total_inserted=source_health.total_inserted + excluded.last_inserted_count
            """,
            (
                int(source_id),
                now,
                now if inserted > 0 else "",
                "",
                "",
                inserted,
                1,
                0,
                inserted,
            ),
        )


def record_source_error(database: object, source_id: int, error: object) -> None:
    ensure_source_health(database)
    now = _now()
    safe = redact_secrets(str(error or ""))[:1200]
    with database.connect() as db:  # type: ignore[attr-defined]
        db.execute(
            """
            INSERT INTO source_health(
                source_id,last_success_at,last_new_at,last_error_at,last_error,
                last_inserted_count,total_checks,total_errors,total_inserted
            ) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_id) DO UPDATE SET
                last_error_at=excluded.last_error_at,
                last_error=excluded.last_error,
                last_inserted_count=0,
                total_checks=source_health.total_checks + 1,
                total_errors=source_health.total_errors + 1
            """,
            (int(source_id), "", "", now, safe, 0, 1, 1, 0),
        )


def source_health_map(database: object) -> dict[int, SourceHealth]:
    ensure_source_health(database)
    with database.connect() as db:  # type: ignore[attr-defined]
        rows = db.execute(
            """
            SELECT source_id,last_success_at,last_new_at,last_error_at,last_error,
                   last_inserted_count,total_checks,total_errors,total_inserted
            FROM source_health
            """
        ).fetchall()
    result: dict[int, SourceHealth] = {}
    for row in rows:
        item = SourceHealth(
            source_id=int(row["source_id"]),
            last_success_at=str(row["last_success_at"] or ""),
            last_new_at=str(row["last_new_at"] or ""),
            last_error_at=str(row["last_error_at"] or ""),
            last_error=str(row["last_error"] or ""),
            last_inserted_count=int(row["last_inserted_count"] or 0),
            total_checks=int(row["total_checks"] or 0),
            total_errors=int(row["total_errors"] or 0),
            total_inserted=int(row["total_inserted"] or 0),
        )
        result[item.source_id] = item
    return result
