from __future__ import annotations

from pathlib import Path

helper = Path(__file__)
target = helper.with_name("apply_v1_1_0_hardening.py")
text = target.read_text(encoding="utf-8")
old = '''def test_topic_feedback_is_separated_by_language_on_legacy_unique_constraint(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    db = Database(path)
    with sqlite3.connect(path) as raw:
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
        raw.commit()
    upgraded = Database(path)
    assert upgraded.record_topic_feedback("Anchor", "Candidate", language="uk")
    assert upgraded.record_topic_feedback("Anchor", "Candidate", language="en")
    assert len(upgraded.list_topic_feedback(language="uk")) == 1
    assert len(upgraded.list_topic_feedback(language="en")) == 1
'''
new = '''def test_topic_feedback_is_separated_by_language_on_legacy_unique_constraint(tmp_path: Path) -> None:
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
'''
if old not in text:
    raise SystemExit("Legacy hardening test anchor not found")
target.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
helper.unlink()
print("Windows-safe v1.1.0 hardening test prepared")
