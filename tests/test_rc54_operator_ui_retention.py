from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from content_agent.config import AppConfig
from content_agent.services.retention import RetentionService
from content_agent.scheduling import KYIV
from content_agent.v2.storage.factory import create_database
from content_agent.v2.ui.tabs.inbox import InboxTabController


def _insert_group_article(db, source_id: int, title: str, published: datetime) -> tuple[int, int]:
    stamp = published.isoformat(timespec="seconds")
    with db.connect() as conn:
        group_id = int(conn.execute(
            "INSERT INTO news_groups(canonical_title,created_at,updated_at) VALUES(?,?,?)",
            (title, stamp, stamp),
        ).lastrowid)
        article_id = int(conn.execute(
            """INSERT INTO articles(
                source_id,group_id,external_id,content_hash,title,url,raw_text,published_at,discovered_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                source_id, group_id, f"ext-{title}", f"hash-{title}", title,
                f"https://example.test/{group_id}", title, stamp, stamp,
            ),
        ).lastrowid)
    return group_id, article_id


def test_rc54_inbox_is_operator_compact_and_time_only() -> None:
    assert InboxTabController.DISPLAY_COLUMNS == ("title", "topic", "sources", "published")
    assert "id" not in InboxTabController.DISPLAY_COLUMNS
    assert "status" not in InboxTabController.DISPLAY_COLUMNS
    assert "source" not in InboxTabController.DISPLAY_COLUMNS
    assert "score" not in InboxTabController.DISPLAY_COLUMNS
    value = InboxTabController._format_time("2026-09-30T12:34:00+00:00")
    assert value.count(":") == 1
    assert "." not in value


def test_rc54_inbox_has_no_hidden_200_group_cap(tmp_path: Path) -> None:
    db = create_database(tmp_path / "many.sqlite3")
    source = db.add_source("rss", "Bulk", "https://example.test/rss")
    now = datetime(2026, 9, 30, 12, tzinfo=KYIV)
    for index in range(205):
        _insert_group_article(db, source, f"bulk-{index}", now - timedelta(minutes=index))
    assert len(db.list_inbox_groups(status="new")) == 205
    assert len(db.list_inbox_groups(status="new", limit=50)) == 50


def test_rc54_retention_deletes_old_news_but_preserves_active_publication(tmp_path: Path) -> None:
    db = create_database(tmp_path / "retention.sqlite3")
    source = db.add_source("rss", "Retention", "https://example.test/retention")
    now = datetime(2026, 9, 30, 14, tzinfo=KYIV)
    old_group, old_article = _insert_group_article(db, source, "old-delete", now - timedelta(days=9))
    recent_group, recent_article = _insert_group_article(db, source, "recent-keep", now - timedelta(days=2))
    protected_group, protected_article = _insert_group_article(db, source, "old-pending", now - timedelta(days=10))
    with db.connect() as conn:
        stamp = now.isoformat(timespec="seconds")
        conn.execute(
            """INSERT INTO publication_batches(
                article_id,scheduled_at,status,lease_owner,lease_until,attempts,cleanup_error,created_at,updated_at
            ) VALUES(?,?,'pending',NULL,NULL,0,NULL,?,?)""",
            (protected_article, stamp, stamp, stamp),
        )

    result = RetentionService(db, days=7).purge(now=now, allow_vacuum=False)
    assert result.deleted_articles == 1
    with db.connect() as conn:
        article_ids = {int(row[0]) for row in conn.execute("SELECT id FROM articles")}
        group_ids = {int(row[0]) for row in conn.execute("SELECT id FROM news_groups")}
        assert int(conn.execute("SELECT COUNT(*) FROM sources WHERE id=?", (source,)).fetchone()[0]) == 1
    assert old_article not in article_ids
    assert old_group not in group_ids
    assert recent_article in article_ids and recent_group in group_ids
    assert protected_article in article_ids and protected_group in group_ids


def test_rc54_retention_preserves_unknown_outcome(tmp_path: Path) -> None:
    db = create_database(tmp_path / "unknown.sqlite3")
    source = db.add_source("rss", "Unknown", "https://example.test/unknown")
    now = datetime(2026, 9, 30, 14, tzinfo=KYIV)
    group_id, article_id = _insert_group_article(db, source, "old-unknown", now - timedelta(days=12))
    with db.connect() as conn:
        stamp = now.isoformat(timespec="seconds")
        batch = int(conn.execute(
            """INSERT INTO publication_batches(
                article_id,scheduled_at,status,lease_owner,lease_until,attempts,cleanup_error,created_at,updated_at
            ) VALUES(?,?,'completed',NULL,NULL,0,NULL,?,?)""",
            (article_id, stamp, stamp, stamp),
        ).lastrowid)
        conn.execute(
            """INSERT INTO publication_targets(
                batch_id,platform,payload_text,status,remote_id,last_error,progress_json,updated_at,outcome
            ) VALUES(?,'telegram','x','failed',NULL,'ambiguous','{}',?,'unknown')""",
            (batch, stamp),
        )
    RetentionService(db, days=7).purge(now=now, allow_vacuum=False)
    with db.connect() as conn:
        assert conn.execute("SELECT 1 FROM articles WHERE id=?", (article_id,)).fetchone() is not None
        assert conn.execute("SELECT 1 FROM news_groups WHERE id=?", (group_id,)).fetchone() is not None


def test_rc54_potential_score_is_not_persisted(tmp_path: Path) -> None:
    db = create_database(tmp_path / "score.sqlite3")
    source = db.add_source("rss", "Score", "https://example.test/score")
    group_id, _article_id = _insert_group_article(
        db, source, "operator decides", datetime(2026, 9, 30, 12, tzinfo=KYIV)
    )
    db.set_group_analysis(group_id, score=99, confidence=100, details={"x": 1}, recommendations=["telegram"])
    group = db.get_group(group_id)
    assert group.explosiveness_score == 0
    assert group.explosiveness_confidence == 0
    assert group.recommended_platforms == []


def test_rc54_platform_and_data_tabs_are_real_modules() -> None:
    platforms = Path("content_agent/v2/ui/tabs/platforms.py").read_text(encoding="utf-8")
    data_tab = Path("content_agent/v2/ui/tabs/data_backups.py").read_text(encoding="utf-8")
    shell = Path("content_agent/v2/ui/manual_topics_window_rc44.py").read_text(encoding="utf-8")
    for label in ("Telegram", "Facebook", "Instagram", "Threads", "LinkedIn", "Google Drive"):
        assert label in platforms
    assert "Платформи" in platforms
    assert "Дані й резервні копії" in data_tab
    assert "PlatformsTabController" in shell
    assert "DataBackupsTabController" in shell
    assert "window_rc54" not in shell.casefold()


def test_rc54_appservices_owns_retention() -> None:
    source = Path("content_agent/app/container.py").read_text(encoding="utf-8")
    assert "retention: RetentionService" in source
    assert "retention.run_startup()" in source


def test_rc54_version_alignment() -> None:
    version = Path("VERSION.txt").read_text(encoding="utf-8").strip()
    public = Path("PUBLIC_VERSION.txt").read_text(encoding="utf-8").strip()
    assert version == public
    assert version.startswith("2.0.0-rc") and int(version.rsplit("rc", 1)[1]) >= 54
    assert f'__version__ = "{version}"' in Path("content_agent/__init__.py").read_text(encoding="utf-8")
