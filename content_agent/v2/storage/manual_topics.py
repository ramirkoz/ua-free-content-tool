from __future__ import annotations

from typing import Iterable


class ManualTopicsMixin:
    """Durable operator-owned topic catalog and RC54 operator data policy."""

    @staticmethod
    def _clean_topic_name(value: object) -> str:
        return " ".join(str(value or "").split()).strip()

    def list_manual_topics(self) -> list[dict[str, object]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,name,created_at,updated_at FROM manual_topics ORDER BY name COLLATE NOCASE,id"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_manual_topic(self, name: str) -> int:
        clean = self._clean_topic_name(name)
        if not clean:
            raise ValueError("Назва теми не може бути порожньою.")
        with self.connect() as db:
            existing = db.execute("SELECT id FROM manual_topics WHERE name=? COLLATE NOCASE", (clean,)).fetchone()
            if existing:
                return int(existing[0])
            cursor = db.execute(
                "INSERT INTO manual_topics(name,created_at,updated_at) VALUES(?,datetime('now'),datetime('now'))",
                (clean,),
            )
        return int(cursor.lastrowid)

    def rename_manual_topic(self, topic_id: int, name: str) -> None:
        clean = self._clean_topic_name(name)
        if not clean:
            raise ValueError("Назва теми не може бути порожньою.")
        with self.connect() as db:
            collision = db.execute(
                "SELECT id FROM manual_topics WHERE name=? COLLATE NOCASE AND id<>?", (clean, int(topic_id))
            ).fetchone()
            if collision:
                raise ValueError("Тема з такою назвою вже існує.")
            cursor = db.execute(
                "UPDATE manual_topics SET name=?,updated_at=datetime('now') WHERE id=?", (clean, int(topic_id))
            )
            if cursor.rowcount != 1:
                raise KeyError(int(topic_id))

    def delete_manual_topic(self, topic_id: int) -> int:
        topic_id = int(topic_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                affected = int(db.execute("SELECT COUNT(*) FROM sources WHERE topic_id=?", (topic_id,)).fetchone()[0] or 0)
                db.execute("UPDATE sources SET topic_id=NULL WHERE topic_id=?", (topic_id,))
                cursor = db.execute("DELETE FROM manual_topics WHERE id=?", (topic_id,))
                if cursor.rowcount != 1:
                    raise KeyError(topic_id)
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return affected

    def set_source_topic(self, source_id: int, topic_id: int | None) -> None:
        source_id = int(source_id)
        value = None if topic_id is None else int(topic_id)
        with self.connect() as db:
            if value is not None and db.execute("SELECT id FROM manual_topics WHERE id=?", (value,)).fetchone() is None:
                raise KeyError(value)
            cursor = db.execute("UPDATE sources SET topic_id=? WHERE id=?", (value, source_id))
            if cursor.rowcount != 1:
                raise KeyError(source_id)

    def source_topic_rows(self, *, enabled_only: bool = False) -> list[dict[str, object]]:
        query = """
            SELECT s.id,s.kind,s.name,s.url,s.enabled,s.last_checked_at,s.topic_id,
                   COALESCE(t.name,'') AS topic_name
            FROM sources s
            LEFT JOIN manual_topics t ON t.id=s.topic_id
        """
        if enabled_only:
            query += " WHERE s.enabled=1"
        query += " ORDER BY s.name COLLATE NOCASE,s.id"
        with self.connect() as db:
            rows = db.execute(query).fetchall()
        return [dict(row) for row in rows]

    def source_topic_map(self) -> dict[int, dict[str, object]]:
        return {int(row["id"]): row for row in self.source_topic_rows()}

    def group_manual_topics(self, group_ids: Iterable[int] | None = None) -> dict[int, dict[str, object]]:
        ids = [] if group_ids is None else list(dict.fromkeys(int(value) for value in group_ids if int(value) > 0))
        query = """
            SELECT a.group_id,s.id AS source_id,s.name AS source_name,
                   t.id AS topic_id,COALESCE(t.name,'') AS topic_name
            FROM articles a
            JOIN sources s ON s.id=a.source_id
            LEFT JOIN manual_topics t ON t.id=s.topic_id
            WHERE a.group_id IS NOT NULL
        """
        params: list[object] = []
        if ids:
            placeholders = ",".join("?" for _ in ids)
            query += f" AND a.group_id IN ({placeholders})"
            params.extend(ids)
        query += " ORDER BY a.group_id,s.name COLLATE NOCASE,s.id"
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        result: dict[int, dict[str, object]] = {}
        for row in rows:
            group_id = int(row["group_id"])
            bucket = result.setdefault(group_id, {"source_ids": [], "source_names": [], "topic_ids": [], "topic_names": []})
            source_id = int(row["source_id"])
            source_name = str(row["source_name"] or "")
            topic_id = row["topic_id"]
            topic_name = str(row["topic_name"] or "")
            if source_id not in bucket["source_ids"]:
                bucket["source_ids"].append(source_id)
                bucket["source_names"].append(source_name)
            if topic_id is not None and int(topic_id) not in bucket["topic_ids"]:
                bucket["topic_ids"].append(int(topic_id))
                bucket["topic_names"].append(topic_name)
        return result

    def set_group_analysis(
        self,
        group_id: int,
        *,
        score: int,
        confidence: int,
        details: dict[str, object],
        recommendations: list[str],
    ) -> None:
        """RC54 compatibility sink: automatic 'potential' scoring is no longer product behavior.

        Historical schema fields stay readable until RC55 cleanup, but active collection/merge
        paths cannot persist or influence an operator-facing score anymore.
        """
        return None

    def list_inbox_groups(
        self,
        *,
        status: str | None = None,
        source_id: int | None = None,
        topic_id: int | None = None,
        search: str = "",
        limit: int | None = None,
    ):
        """Return all matching Inbox groups unless an explicit caller limit is given."""
        query = """
            SELECT g.*,
                   COUNT(a.id) AS source_count,
                   MIN(a.published_at) AS first_published_at,
                   MAX(a.published_at) AS last_published_at
            FROM news_groups g
            JOIN articles a ON a.group_id=g.id
        """
        where: list[str] = []
        params: list[object] = []
        if status == "approved":
            where.append(
                """g.status='approved' AND (
                    julianday(g.updated_at) >= julianday('now','-1 day') OR EXISTS (
                        SELECT 1 FROM publication_batches b
                        JOIN articles qa ON qa.id=b.article_id
                        WHERE qa.group_id=g.id AND b.status IN ('pending','in_progress','paused')
                    )
                )"""
            )
        elif status:
            where.append("g.status=?")
            params.append(str(status))
        else:
            where.append(
                """g.status IN ('new','draft') OR (g.status='approved' AND (
                    julianday(g.updated_at) >= julianday('now','-1 day') OR EXISTS (
                        SELECT 1 FROM publication_batches b
                        JOIN articles qa ON qa.id=b.article_id
                        WHERE qa.group_id=g.id AND b.status IN ('pending','in_progress','paused')
                    )
                ))"""
            )
        if source_id is not None:
            where.append("EXISTS (SELECT 1 FROM articles fs WHERE fs.group_id=g.id AND fs.source_id=?)")
            params.append(int(source_id))
        if topic_id is not None:
            where.append(
                """EXISTS (
                    SELECT 1 FROM articles ft
                    JOIN sources fts ON fts.id=ft.source_id
                    WHERE ft.group_id=g.id AND fts.topic_id=?
                )"""
            )
            params.append(int(topic_id))
        for token in [part for part in str(search or "").split() if part]:
            pattern = f"%{token.casefold()}%"
            where.append(
                """EXISTS (
                    SELECT 1 FROM articles fa
                    WHERE fa.group_id=g.id AND (
                        CASEFOLD(g.canonical_title) LIKE ? OR CASEFOLD(g.headline) LIKE ? OR CASEFOLD(g.rewrite_text) LIKE ?
                        OR CASEFOLD(fa.title) LIKE ? OR CASEFOLD(fa.raw_text) LIKE ?
                    )
                )"""
            )
            params.extend([pattern, pattern, pattern, pattern, pattern])
        if where:
            query += " WHERE " + " AND ".join(f"({item})" for item in where)
        query += " GROUP BY g.id ORDER BY COALESCE(MAX(a.published_at),g.updated_at) DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(max(1, min(5000, int(limit))))
        with self.connect() as db:
            db.create_function("CASEFOLD", 1, lambda value: str(value or "").casefold(), deterministic=True)
            rows = db.execute(query, params).fetchall()
        return [self._group_from_row(row, []) for row in rows]


__all__ = ["ManualTopicsMixin"]
