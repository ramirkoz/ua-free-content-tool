from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .database_v1_4_runtime import Database as V14RuntimeDatabase


class Database(V14RuntimeDatabase):
    """RC4 read helpers for grouped UI views without changing publication storage."""

    def topic_contexts(self, group_ids: Iterable[int]) -> dict[int, dict[str, object]]:
        ids = sorted({int(value) for value in group_ids if int(value) > 0})
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT g.id AS group_id,g.canonical_title,
                       a.id AS article_id,a.title AS article_title,a.raw_text
                FROM news_groups g
                LEFT JOIN articles a ON a.group_id=g.id
                WHERE g.id IN ({placeholders})
                ORDER BY g.id,a.id
                """,
                ids,
            ).fetchall()

        result: dict[int, dict[str, object]] = {}
        body_parts: dict[int, list[str]] = defaultdict(list)
        for row in rows:
            group_id = int(row["group_id"])
            item = result.setdefault(
                group_id,
                {
                    "canonical_title": str(row["canonical_title"] or ""),
                    "article_titles": [],
                    "body": "",
                },
            )
            title = str(row["article_title"] or "").strip()
            if title:
                titles = item["article_titles"]
                if isinstance(titles, list) and title not in titles:
                    titles.append(title)
            raw = str(row["raw_text"] or "").strip()
            if raw:
                # Topic classification needs semantics, not an unlimited mirror of
                # every source. A bounded slice keeps refreshes cheap and stable.
                body_parts[group_id].append(raw[:6000])

        for group_id, item in result.items():
            item["body"] = "\n\n".join(body_parts.get(group_id, []))[:24000]
        return result

    def group_ids_for_batches(self, batch_ids: Iterable[int]) -> dict[int, int]:
        ids = sorted({int(value) for value in batch_ids if int(value) > 0})
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT b.id AS batch_id,a.group_id
                FROM publication_batches b
                JOIN articles a ON a.id=b.article_id
                WHERE b.id IN ({placeholders})
                """,
                ids,
            ).fetchall()
        return {int(row["batch_id"]): int(row["group_id"]) for row in rows}
