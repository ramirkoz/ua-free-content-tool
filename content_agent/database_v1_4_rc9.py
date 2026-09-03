from __future__ import annotations

from collections.abc import Iterable

from .database_v1_4_rc4 import Database as Rc4Database


class Database(Rc4Database):
    """RC9 source-management operations without a schema migration."""

    def update_source(self, source_id: int, *, kind: str, name: str, url: str) -> None:
        source_kind = str(kind or "").strip().casefold()
        source_name = str(name or "").strip()
        source_url = str(url or "").strip()
        if source_kind not in {"rss", "telegram", "url"}:
            raise ValueError("Тип джерела має бути rss, telegram або url.")
        if not source_name or not source_url:
            raise ValueError("Назва та адреса джерела не можуть бути порожніми.")
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE sources SET kind=?,name=?,url=?,last_checked_at=NULL WHERE id=?",
                (source_kind, source_name, source_url, int(source_id)),
            )
            if int(cursor.rowcount or 0) != 1:
                raise KeyError(f"Джерело #{int(source_id)} не знайдено.")

    def delete_sources(self, source_ids: Iterable[int]) -> int:
        ids = sorted({int(value) for value in source_ids if int(value) > 0})
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                cursor = db.execute(f"DELETE FROM sources WHERE id IN ({placeholders})", ids)
                db.execute(
                    "DELETE FROM news_groups "
                    "WHERE id NOT IN (SELECT DISTINCT group_id FROM articles WHERE group_id IS NOT NULL)"
                )
                deleted = max(0, int(cursor.rowcount or 0))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return deleted
