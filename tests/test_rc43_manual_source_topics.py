from __future__ import annotations

from content_agent.clean_import import _STABLE_TABLES
from content_agent.database import Database as BaseDatabase
from content_agent.v2.storage.manual_topics import ManualTopicsMixin
from content_agent.v2.storage.migrations import apply_v2_migrations
from content_agent.v2.ui.manual_topics_window import UNASSIGNED_TOPIC, _ManualSourceTopicStore


class TopicDatabase(ManualTopicsMixin, BaseDatabase):
    """Legacy regression fixture composed through the current numbered migration contract."""

    def __init__(self, path):
        super().__init__(path)
        apply_v2_migrations(self)


def _group_with_article(db: TopicDatabase, source_id: int, *, suffix: str) -> int:
    with db.connect() as con:
        now = "2026-09-28T12:00:00+00:00"
        cursor = con.execute(
            "INSERT INTO news_groups(canonical_title,created_at,updated_at) VALUES(?,?,?)",
            (f"Group {suffix}", now, now),
        )
        group_id = int(cursor.lastrowid)
        con.execute(
            """
            INSERT INTO articles(
                source_id,group_id,external_id,content_hash,title,url,raw_text,discovered_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                int(source_id), group_id, f"ext-{suffix}", f"hash-{suffix}",
                f"Title {suffix}", f"https://example.test/{suffix}", f"Body {suffix}", now,
            ),
        )
    return group_id


def test_manual_topics_are_arbitrary_and_persist_on_source(tmp_path):
    db = TopicDatabase(tmp_path / "content.sqlite3")
    culture = db.create_manual_topic("Культура / дивні штуки")
    tech = db.create_manual_topic("AI та технології")
    assert culture != tech

    source_id = db.add_source("rss", "Example", "https://example.test/feed")
    db.set_source_topic(source_id, culture)

    rows = db.source_topic_rows()
    row = next(item for item in rows if int(item["id"]) == source_id)
    assert int(row["topic_id"]) == culture
    assert row["topic_name"] == "Культура / дивні штуки"

    reopened = TopicDatabase(tmp_path / "content.sqlite3")
    row = next(item for item in reopened.source_topic_rows() if int(item["id"]) == source_id)
    assert int(row["topic_id"]) == culture
    assert row["topic_name"] == "Культура / дивні штуки"


def test_rc42_database_upgrades_in_place_without_losing_existing_sources(tmp_path):
    path = tmp_path / "content.sqlite3"
    old = BaseDatabase(path)
    source_id = old.add_source("rss", "Existing RC42 source", "https://legacy.test/feed")
    with old.connect() as con:
        columns_before = {str(row[1]) for row in con.execute("PRAGMA table_info(sources)").fetchall()}
        assert "topic_id" not in columns_before

    upgraded = TopicDatabase(path)
    with upgraded.connect() as con:
        columns_after = {str(row[1]) for row in con.execute("PRAGMA table_info(sources)").fetchall()}
        assert "topic_id" in columns_after
        assert con.execute("SELECT 1 FROM manual_topics LIMIT 1").fetchone() is None
    row = next(item for item in upgraded.source_topic_rows() if int(item["id"]) == source_id)
    assert row["name"] == "Existing RC42 source"
    assert row["topic_id"] is None


def test_manual_topics_are_part_of_future_clean_import_contract():
    assert "manual_topics" in _STABLE_TABLES
    assert _STABLE_TABLES.index("manual_topics") < _STABLE_TABLES.index("sources")


def test_group_topics_are_derived_only_from_member_sources(tmp_path):
    db = TopicDatabase(tmp_path / "content.sqlite3")
    topic_a = db.create_manual_topic("Тема А")
    topic_b = db.create_manual_topic("Тема Б")
    source_a = db.add_source("rss", "Source A", "https://a.test/feed")
    source_b = db.add_source("rss", "Source B", "https://b.test/feed")
    db.set_source_topic(source_a, topic_a)
    db.set_source_topic(source_b, topic_b)

    group_id = _group_with_article(db, source_a, suffix="a")
    with db.connect() as con:
        con.execute(
            """
            INSERT INTO articles(
                source_id,group_id,external_id,content_hash,title,url,raw_text,discovered_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                source_b, group_id, "ext-b", "hash-b", "Title B",
                "https://b.test/item", "Body B", "2026-09-28T12:01:00+00:00",
            ),
        )

    info = db.group_manual_topics([group_id])[group_id]
    assert set(info["source_ids"]) == {source_a, source_b}
    assert set(info["topic_ids"]) == {topic_a, topic_b}
    assert set(info["topic_names"]) == {"Тема А", "Тема Б"}


def test_renaming_topic_updates_source_and_inbox_view_without_reclassifying(tmp_path):
    db = TopicDatabase(tmp_path / "content.sqlite3")
    topic_id = db.create_manual_topic("Стара назва")
    source_id = db.add_source("rss", "Source", "https://source.test/feed")
    db.set_source_topic(source_id, topic_id)
    group_id = _group_with_article(db, source_id, suffix="rename")

    db.rename_manual_topic(topic_id, "Нова назва")

    source_row = next(item for item in db.source_topic_rows() if int(item["id"]) == source_id)
    group_row = db.group_manual_topics([group_id])[group_id]
    assert source_row["topic_name"] == "Нова назва"
    assert group_row["topic_names"] == ["Нова назва"]


def test_deleting_topic_unassigns_sources_but_never_deletes_news(tmp_path):
    db = TopicDatabase(tmp_path / "content.sqlite3")
    topic_id = db.create_manual_topic("Тимчасова")
    source_id = db.add_source("rss", "Source", "https://source.test/rss")
    db.set_source_topic(source_id, topic_id)
    group_id = _group_with_article(db, source_id, suffix="keep")

    affected = db.delete_manual_topic(topic_id)

    assert affected == 1
    source_row = next(item for item in db.source_topic_rows() if int(item["id"]) == source_id)
    assert source_row["topic_id"] is None
    assert source_row["topic_name"] == ""
    assert group_id in db.group_manual_topics([group_id])
    with db.connect() as con:
        assert int(con.execute("SELECT COUNT(*) FROM articles WHERE group_id=?", (group_id,)).fetchone()[0]) == 1


def test_old_automatic_topic_store_is_neutralized_in_rc43():
    store = _ManualSourceTopicStore()
    decision, changed = store.resolve(123, {"title": "Президент відкрив наукову лабораторію"})
    assert decision.topic == UNASSIGNED_TOPIC
    assert changed is False
