from __future__ import annotations

from pathlib import Path

from content_agent.v2.storage.factory import create_database


def _seed_inbox(db) -> tuple[int, int, int, int]:
    topic_a = db.create_manual_topic("Технології")
    topic_b = db.create_manual_topic("Наука")
    source_a = db.add_source("rss", "Source Alpha", "https://example.test/a")
    source_b = db.add_source("rss", "Source Beta", "https://example.test/b")
    db.set_source_topic(source_a, topic_a)
    db.set_source_topic(source_b, topic_b)
    with db.connect() as conn:
        g1 = int(conn.execute(
            "INSERT INTO news_groups(canonical_title,created_at,updated_at) VALUES(?,?,?)",
            ("Alpha mission", "2026-09-30T10:00:00+00:00", "2026-09-30T10:00:00+00:00"),
        ).lastrowid)
        g2 = int(conn.execute(
            "INSERT INTO news_groups(canonical_title,created_at,updated_at) VALUES(?,?,?)",
            ("Beta laboratory", "2026-09-30T11:00:00+00:00", "2026-09-30T11:00:00+00:00"),
        ).lastrowid)
        conn.execute(
            """INSERT INTO articles(
                source_id,group_id,external_id,content_hash,title,url,raw_text,published_at,discovered_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                source_a, g1, "a-1", "hash-a-1", "Alpha rocket", "https://example.test/a/1",
                "Launch completed successfully near orbit.", "2026-09-30T09:55:00+00:00",
                "2026-09-30T10:00:00+00:00",
            ),
        )
        conn.execute(
            """INSERT INTO articles(
                source_id,group_id,external_id,content_hash,title,url,raw_text,published_at,discovered_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                source_b, g2, "b-1", "hash-b-1", "Beta telescope", "https://example.test/b/1",
                "Scientists published a new observation.", "2026-09-30T10:55:00+00:00",
                "2026-09-30T11:00:00+00:00",
            ),
        )
    return source_a, source_b, topic_a, topic_b


def test_rc53_source_topic_search_filters_are_sql_backed(tmp_path: Path) -> None:
    db = create_database(tmp_path / "rc53.sqlite3")
    source_a, source_b, topic_a, topic_b = _seed_inbox(db)
    assert [g.canonical_title for g in db.list_inbox_groups(source_id=source_a)] == ["Alpha mission"]
    assert [g.canonical_title for g in db.list_inbox_groups(source_id=source_b)] == ["Beta laboratory"]
    assert [g.canonical_title for g in db.list_inbox_groups(topic_id=topic_a)] == ["Alpha mission"]
    assert [g.canonical_title for g in db.list_inbox_groups(topic_id=topic_b)] == ["Beta laboratory"]
    assert [g.canonical_title for g in db.list_inbox_groups(search="Alpha launch")] == ["Alpha mission"]
    assert db.list_inbox_groups(search="Alpha scientists") == []
    assert [
        g.canonical_title
        for g in db.list_inbox_groups(source_id=source_a, topic_id=topic_a, search="rocket orbit")
    ] == ["Alpha mission"]


def test_rc53_canonical_shell_uses_controller_and_shared_components() -> None:
    shell = Path("content_agent/v2/ui/manual_topics_window_rc44.py").read_text(encoding="utf-8")
    controller = Path("content_agent/v2/ui/tabs/inbox.py").read_text(encoding="utf-8")
    components = Path("content_agent/v2/ui/components.py").read_text(encoding="utf-8")
    assert "InboxTabController" in shell
    assert "FilterBar" in shell
    assert "StatusBar" in shell
    assert "PublicationStatus" in shell
    assert "list_inbox_groups" in controller
    assert "class InboxFilterState" in controller
    assert "class InboxTabController" in controller
    assert "class FilterBar(ActionBar)" in components
    assert "class PublicationStatus" in components
    assert "class StatusBar" in components


def test_rc53_does_not_add_version_numbered_runtime_layer() -> None:
    offenders = [path for path in Path("content_agent").rglob("*.py") if "rc53" in path.name.casefold()]
    assert offenders == []


def test_rc53_package_version_is_aligned() -> None:
    public = Path("PUBLIC_VERSION.txt").read_text(encoding="utf-8").strip()
    internal = Path("VERSION.txt").read_text(encoding="utf-8").strip()
    package = Path("content_agent/__init__.py").read_text(encoding="utf-8")
    assert public == internal
    assert f'__version__ = "{public}"' in package
