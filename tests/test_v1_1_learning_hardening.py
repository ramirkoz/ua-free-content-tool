from __future__ import annotations

import sqlite3
from pathlib import Path

from content_agent.collectors import CollectedArticle
from content_agent.database import Database


def _group(db: Database) -> int:
    source_id = db.add_source("rss", "Source", "https://example.com/feed")
    db.insert_collected(
        source_id,
        [CollectedArticle("one", "Headline", "https://example.com/one", "Source body", None)],
        enforce_today=False,
    )
    return db.list_groups()[0].id


def test_topic_feedback_is_separated_by_language_on_legacy_unique_constraint(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    upgraded = Database(path)
    with upgraded.connect() as raw:
        raw.execute("DROP TABLE topic_merge_feedback")
        raw.execute(
            """
            CREATE TABLE topic_merge_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                anchor_signature TEXT NOT NULL,
                candidate_signature TEXT NOT NULL,
                decision TEXT NOT NULL CHECK(decision IN ('merged','not_related')),
                anchor_text TEXT NOT NULL,
                candidate_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(anchor_signature,candidate_signature,decision)
            )
            """
        )
        raw.execute("PRAGMA user_version=7")
    upgraded.initialize()
    assert upgraded.record_topic_feedback("Anchor", "Candidate", language="uk")
    assert upgraded.record_topic_feedback("Anchor", "Candidate", language="en")
    assert len(upgraded.list_topic_feedback(language="uk")) == 1
    assert len(upgraded.list_topic_feedback(language="en")) == 1


def test_learning_export_import_roundtrips_content_exclusions(tmp_path: Path) -> None:
    source = Database(tmp_path / "source.sqlite3")
    group_id = _group(source)
    source.remember_content_exclusions([group_id])
    exported = source.export_learning_data(tmp_path / "learning.json")

    target = Database(tmp_path / "target.sqlite3")
    counts = target.import_learning_data(exported)
    assert counts["content_exclusions"] >= 1
    assert target.content_exclusion_count() == source.content_exclusion_count()


def test_ui_connectors_record_user_learning_decisions() -> None:
    source = (Path(__file__).parents[1] / "content_agent" / "ui" / "main_window.py").read_text(
        encoding="utf-8"
    )
    assert '"content_excluded"' in source
    assert '"exclusion_restored"' in source
    assert '"manual_groups_merged"' in source
    assert '"publication_approved"' in source
