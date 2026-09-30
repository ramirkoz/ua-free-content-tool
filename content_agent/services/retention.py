from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from ..paths import data_dir
from ..scheduling import KYIV


@dataclass(frozen=True, slots=True)
class RetentionResult:
    cutoff: str
    deleted_articles: int
    deleted_groups: int
    vacuumed: bool


class RetentionService:
    """Keep operational news data bounded without touching durable editorial state."""

    def __init__(self, database: Any, *, days: int = 7) -> None:
        self.db = database
        self.days = max(1, int(days))
        self._state_path = data_dir() / "v2" / "retention_state.json"

    def _cutoff(self, now: datetime | None = None) -> datetime:
        local = (now or datetime.now(KYIV)).astimezone(KYIV)
        start_today = datetime.combine(local.date(), time.min, tzinfo=KYIV)
        return start_today - timedelta(days=self.days)

    def _last_vacuum_date(self) -> str:
        try:
            value = json.loads(self._state_path.read_text(encoding="utf-8"))
            return str(value.get("last_vacuum_date") or "") if isinstance(value, dict) else ""
        except Exception:
            return ""

    def _record_vacuum(self, value: str) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"last_vacuum_date": value}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._state_path)
        except Exception:
            return

    def purge(self, *, now: datetime | None = None, allow_vacuum: bool = True) -> RetentionResult:
        cutoff = self._cutoff(now)
        cutoff_iso = cutoff.isoformat(timespec="seconds")
        deleted_articles = 0
        deleted_groups = 0

        with self.db.connect() as conn:
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(publication_targets)").fetchall()}
            unknown_clause = " OR t.outcome='unknown'" if "outcome" in columns else ""
            conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = conn.execute(
                    f"""
                    DELETE FROM articles
                    WHERE julianday(COALESCE(published_at, discovered_at)) < julianday(?)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM publication_batches b
                          LEFT JOIN publication_targets t ON t.batch_id=b.id
                          WHERE b.article_id=articles.id
                            AND (b.status IN ('pending','in_progress','paused'){unknown_clause})
                      )
                    """,
                    (cutoff_iso,),
                )
                deleted_articles = max(0, int(cursor.rowcount or 0))
                cursor = conn.execute(
                    """
                    DELETE FROM news_groups
                    WHERE NOT EXISTS (SELECT 1 FROM articles a WHERE a.group_id=news_groups.id)
                      AND julianday(updated_at) < julianday(?)
                    """,
                    (cutoff_iso,),
                )
                deleted_groups = max(0, int(cursor.rowcount or 0))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        today = (now or datetime.now(KYIV)).astimezone(KYIV).date().isoformat()
        vacuumed = False
        if allow_vacuum and (deleted_articles or deleted_groups) and self._last_vacuum_date() != today:
            with self.db.connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("VACUUM")
            self._record_vacuum(today)
            vacuumed = True

        return RetentionResult(
            cutoff=cutoff_iso,
            deleted_articles=deleted_articles,
            deleted_groups=deleted_groups,
            vacuumed=vacuumed,
        )

    def run_startup(self) -> RetentionResult:
        return self.purge(allow_vacuum=True)


__all__ = ["RetentionResult", "RetentionService"]
