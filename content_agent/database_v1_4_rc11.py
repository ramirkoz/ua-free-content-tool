from __future__ import annotations

from .database_v1_4_rc10 import Database as Rc10Database


class Database(Rc10Database):
    """RC11 Inbox reads the full working set before any user-selected UI sort."""

    def list_groups(self, status: str | None = None, limit: int | None = None):
        # RC10 inherited the historical 200-row default. That makes a visual
        # sort by source count operate on a recency-truncated subset and can
        # temporarily hide a freshly merged block whose articles are older.
        # Explicit analytical callers still pass their own bounded limit.
        effective_limit = 2_147_483_647 if limit is None else max(1, int(limit))
        return super().list_groups(status=status, limit=effective_limit)
