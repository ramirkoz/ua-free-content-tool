from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from content_agent.database import _iso, _now
from content_agent.database_rc14 import Database, PUBLICATION_HISTORY_RETENTION_DAYS


def _seed_published(db: Database, *, age_days: int, platform: str = "telegram") -> tuple[int, int, int]:
    source_id = db.add_source("rss", f"source-{age_days}", f"https://example.com/{age_days}.xml")
    now = _now()
    with db.connect() as conn:
        group_id = int(conn.execute(
            "INSERT INTO news_groups(canonical_title,status,created_at,updated_at) VALUES(?,?,?,?)",
            (f"group-{age_days}", "approved", _iso(now), _iso(now)),
        ).lastrowid)
        article_id = int(conn.execute(
            """
            INSERT INTO articles(source_id,group_id,external_id,content_hash,title,url,raw_text,published_at,discovered_at,status)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (source_id, group_id, f"ext-{age_days}", f"hash-{age_days}", "title", "https://example.com/a", "body", _iso(now), _iso(now), "approved"),
        ).lastrowid)
        batch_id = int(conn.execute(
            "INSERT INTO publication_batches(article_id,scheduled_at,status,created_at,updated_at) VALUES(?,?,?,?,?)",
            (article_id, _iso(now - timedelta(days=age_days)), "completed", _iso(now), _iso(now)),
        ).lastrowid)
        conn.execute(
            "INSERT INTO publication_targets(batch_id,platform,payload_text,status,remote_id,updated_at) VALUES(?,?,?,?,?,?)",
            (batch_id, platform, "text", "sent", f"remote-{age_days}", _iso(now - timedelta(days=age_days))),
        )
    return group_id, article_id, batch_id


def test_publication_history_is_bounded_to_seven_days(tmp_path: Path) -> None:
    db = Database(tmp_path / "content.sqlite3")
    _seed_published(db, age_days=2)
    _seed_published(db, age_days=9)
    rows = db.list_publication_history(limit=100)
    assert len(rows) == 1
    assert rows[0]["published_at"]
    assert PUBLICATION_HISTORY_RETENTION_DAYS == 7


def test_old_history_moves_to_archive_tables_and_leaves_live_queue(tmp_path: Path) -> None:
    db = Database(tmp_path / "content.sqlite3")
    _group_id, _article_id, old_batch = _seed_published(db, age_days=9)
    archived = db.archive_old_publication_history()
    assert archived == 1
    with db.connect() as conn:
        assert conn.execute("SELECT 1 FROM publication_batches WHERE id=?", (old_batch,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM archived_publication_batches WHERE batch_id=?", (old_batch,)).fetchone() is not None
        assert conn.execute("SELECT 1 FROM archived_publication_targets WHERE batch_id=?", (old_batch,)).fetchone() is not None


def test_archived_sent_target_still_blocks_duplicate_publication(tmp_path: Path) -> None:
    db = Database(tmp_path / "content.sqlite3")
    group_id, article_id, _batch_id = _seed_published(db, age_days=9)
    assert db.archive_old_publication_history() == 1
    result = db.queue_targets(article_id, _iso(_now() + timedelta(hours=1)), {"telegram": "new text"})
    assert result.created is False
    assert result.status == "completed"
    assert result.already_sent == ["telegram"]
    assert db.target_statuses_for_group(group_id)["telegram"] == "sent"


def test_rc14_source_has_no_worker_thread_tk_after_for_threads() -> None:
    source = Path("content_agent/ui/rc14_window.py").read_text(encoding="utf-8")
    start = source.index("    def connect_threads")
    end = source.index("    def close", start)
    block = source[start:end]
    assert "self.root.after(\n" not in block
    assert "self._post_ui(" in block
