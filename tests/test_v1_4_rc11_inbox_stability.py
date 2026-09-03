from __future__ import annotations

from pathlib import Path

from content_agent.database import _iso
from content_agent.database_v1_4_rc11 import Database
from content_agent.ui.v1_4_rc11_window import MainWindow


class _FakeInboxTree:
    def __init__(self, source_counts: list[int]) -> None:
        self.rows = [str(index + 1) for index in range(len(source_counts))]
        self.values = {
            iid: {"sources": str(value), "title": f"row {iid}"}
            for iid, value in zip(self.rows, source_counts)
        }
        self.headings = {"sources": "Джерел", "title": "Подія"}

    def get_children(self, parent: str = "") -> tuple[str, ...]:
        assert parent == ""
        return tuple(self.rows)

    def set(self, iid: str, column: str) -> str:
        return self.values[iid][column]

    def move(self, iid: str, parent: str, position: int) -> None:
        assert parent == ""
        self.rows.remove(iid)
        self.rows.insert(position, iid)

    def cget(self, key: str):
        if key == "columns":
            return ("title", "sources")
        raise KeyError(key)

    def heading(self, column: str, option: str | None = None, **kwargs):
        if "text" in kwargs:
            self.headings[column] = str(kwargs["text"])
        if option == "text":
            return self.headings[column]
        return None


def _seed_many(db: Database, *, source_id: int, count: int, published_at: str, start_index: int = 0) -> list[int]:
    ids: list[int] = []
    with db.connect() as con:
        now = _iso()
        con.execute("BEGIN IMMEDIATE")
        try:
            for offset in range(count):
                index = start_index + offset
                cursor = con.execute(
                    "INSERT INTO news_groups(canonical_title,status,created_at,updated_at) VALUES(?,?,?,?)",
                    (f"Story {index}", "new", now, now),
                )
                group_id = int(cursor.lastrowid)
                ids.append(group_id)
                con.execute(
                    """
                    INSERT INTO articles(
                        source_id,group_id,external_id,content_hash,title,url,raw_text,
                        published_at,discovered_at,status,headline,fact_card,rewrite_text,platform_texts_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,'new','','','','{}')
                    """,
                    (
                        source_id, group_id, f"external-{index}", f"hash-{index}",
                        f"Story {index}", f"https://example.com/{index}", f"Body {index}",
                        published_at, now,
                    ),
                )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return ids


def test_rc11_default_inbox_read_is_not_pretruncated_to_200(tmp_path: Path) -> None:
    db = Database(tmp_path / "rc11.sqlite3")
    source_id = db.add_source("rss", "Source", "https://example.com/feed")
    now = _iso()
    _seed_many(db, source_id=source_id, count=230, published_at=now)

    assert len(db.list_groups(limit=200)) == 200
    assert len(db.list_groups()) == 230


def test_rc11_old_dated_merged_like_group_stays_in_full_inbox_read(tmp_path: Path) -> None:
    db = Database(tmp_path / "rc11-visibility.sqlite3")
    source_id = db.add_source("rss", "Source", "https://example.com/feed")
    recent = _iso()
    _seed_many(db, source_id=source_id, count=205, published_at=recent)
    old_group = _seed_many(
        db, source_id=source_id, count=1,
        published_at="2026-01-01T00:00:00+00:00", start_index=999,
    )[0]

    truncated_ids = {group.id for group in db.list_groups(limit=200)}
    full_ids = {group.id for group in db.list_groups()}

    assert old_group not in truncated_ids
    assert old_group in full_ids


def test_rc11_inbox_multisort_keeps_new_rows_in_numeric_source_order() -> None:
    window = MainWindow.__new__(MainWindow)
    window.groups_tree = _FakeInboxTree([8, 8, 6, 1, 5, 5])  # type: ignore[assignment]
    window._inbox_sort_state = [("sources", True)]
    window.config = type("Config", (), {"ui_language": "uk"})()

    window._apply_inbox_sort()

    counts = [int(window.groups_tree.set(iid, "sources")) for iid in window.groups_tree.get_children("")]
    assert counts == [8, 8, 6, 5, 5, 1]


def test_rc11_is_schema_neutral() -> None:
    source = Path(__file__).parents[1] / "content_agent" / "database.py"
    assert "DATABASE_SCHEMA_VERSION = 8" in source.read_text(encoding="utf-8")
