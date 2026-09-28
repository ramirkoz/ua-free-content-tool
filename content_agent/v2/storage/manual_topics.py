from __future__ import annotations

from typing import Iterable


class ManualTopicsMixin:
    """Durable operator-owned topic catalog and per-source assignment.

    Topics are deliberately source metadata, not an AI classification result.
    A source owns zero or one manually selected topic. Inbox groups derive their
    visible/filterable topics from the sources of their member articles.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._ensure_manual_topics_schema()

    def _ensure_manual_topics_schema(self) -> None:
        with self.connect() as db:
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
            columns = {str(row[1]) for row in db.execute("PRAGMA table_info(sources)").fetchall()}
            if "topic_id" not in columns:
                db.execute("ALTER TABLE sources ADD COLUMN topic_id INTEGER")
            db.execute("CREATE INDEX IF NOT EXISTS idx_sources_topic_id ON sources(topic_id)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_manual_topics_name ON manual_topics(name COLLATE NOCASE)")

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
            existing = db.execute(
                "SELECT id FROM manual_topics WHERE name=? COLLATE NOCASE",
                (clean,),
            ).fetchone()
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
                "SELECT id FROM manual_topics WHERE name=? COLLATE NOCASE AND id<>?",
                (clean, int(topic_id)),
            ).fetchone()
            if collision:
                raise ValueError("Тема з такою назвою вже існує.")
            cursor = db.execute(
                "UPDATE manual_topics SET name=?,updated_at=datetime('now') WHERE id=?",
                (clean, int(topic_id)),
            )
            if cursor.rowcount != 1:
                raise KeyError(int(topic_id))

    def delete_manual_topic(self, topic_id: int) -> int:
        topic_id = int(topic_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                affected = int(
                    db.execute("SELECT COUNT(*) FROM sources WHERE topic_id=?", (topic_id,)).fetchone()[0] or 0
                )
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
            if value is not None:
                topic = db.execute("SELECT id FROM manual_topics WHERE id=?", (value,)).fetchone()
                if topic is None:
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
            bucket = result.setdefault(
                group_id,
                {"source_ids": [], "source_names": [], "topic_ids": [], "topic_names": []},
            )
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


__all__ = ["ManualTopicsMixin"]
