from __future__ import annotations

from collections.abc import Iterable

from .database_v1_4_rc14 import Database as Rc14Database


class Database(Rc14Database):
    """RC15 Inbox source filtering without a schema migration."""

    def source_names_for_group_ids(self, group_ids: Iterable[int]) -> dict[int, tuple[str, ...]]:
        """Return the distinct source names attached to each requested group.

        The query is intentionally lightweight: Inbox filtering needs only source
        identity, not full article hydration. Missing/deleted group ids are simply
        absent from the result.
        """
        ordered: list[int] = []
        for raw in group_ids:
            group_id = int(raw)
            if group_id > 0 and group_id not in ordered:
                ordered.append(group_id)
        if not ordered:
            return {}

        names_by_group: dict[int, list[str]] = {group_id: [] for group_id in ordered}
        with self.connect() as db:
            for start in range(0, len(ordered), 400):
                chunk = ordered[start:start + 400]
                placeholders = ",".join("?" for _ in chunk)
                rows = db.execute(
                    f"""
                    SELECT a.group_id AS group_id, s.name AS source_name
                    FROM articles a
                    JOIN sources s ON s.id=a.source_id
                    WHERE a.group_id IN ({placeholders})
                    GROUP BY a.group_id, s.id, s.name
                    ORDER BY s.name COLLATE NOCASE, s.id
                    """,
                    chunk,
                ).fetchall()
                for row in rows:
                    group_id = int(row["group_id"])
                    source_name = str(row["source_name"] or "").strip()
                    if source_name and source_name not in names_by_group.setdefault(group_id, []):
                        names_by_group[group_id].append(source_name)

        return {
            group_id: tuple(names)
            for group_id, names in names_by_group.items()
            if names
        }
