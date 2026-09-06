from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from .database_v1_4_rc18 import Database as Rc18Database
from .scheduling import KYIV


class Database(Rc18Database):
    """RC21 restores the full current-day Inbox and exposes today's raw flow count."""

    def list_groups(self, status: str | None = None, limit: int | None = None):
        """Do not silently truncate the working Inbox to the newest 200 blocks.

        RC18 accidentally reintroduced a 200-row default while adding daily rollover.
        Archive remains bounded by default; every working Inbox filter reads the full
        current-day set before UI sorting/filtering.
        """
        if status == "archived" and limit is None:
            return super().list_groups(status=status, limit=200)
        effective_limit = 2_147_483_647 if limit is None else max(1, int(limit))
        return super().list_groups(status=status, limit=effective_limit)

    def count_today_articles(self, *, now: datetime | None = None) -> int:
        """Count raw news items collected for the current working calendar day.

        ``discovered_at`` is stored canonically in UTC and gives us a cheap bounded
        candidate set. Publication time remains authoritative for the day check, with
        discovery time used only when the source has no trustworthy publication time.
        """
        current = (now or datetime.now(KYIV)).astimezone(KYIV)
        start_local = datetime.combine(current.date(), time.min, tzinfo=KYIV)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(timezone.utc).isoformat(timespec="seconds")
        end_utc = end_local.astimezone(timezone.utc).isoformat(timespec="seconds")

        with self.connect() as db:
            rows = db.execute(
                """
                SELECT published_at, discovered_at
                FROM articles
                WHERE julianday(discovered_at) >= julianday(?)
                  AND julianday(discovered_at) < julianday(?)
                """,
                (start_utc, end_utc),
            ).fetchall()

        return sum(
            1
            for row in rows
            if self._article_is_today(row["published_at"], row["discovered_at"], now=current)
        )
