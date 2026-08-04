from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8", newline="\n")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one occurrence, found {count}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


# Language-salt legacy signatures. Existing v1.0 UNIQUE constraints then remain
# safe and permit independent Ukrainian and English learning records without a
# destructive table rebuild.
replace_once(
    "content_agent/database.py",
    '        fingerprint = hashlib.sha256(source_text.encode("utf-8")).hexdigest()\n',
    '        fingerprint = hashlib.sha256(f"{lang}\\0{source_text}".encode("utf-8")).hexdigest()\n',
)
replace_once(
    "content_agent/database.py",
    '''        left_sig = hashlib.sha256(left.encode("utf-8")).hexdigest()
        right_sig = hashlib.sha256(right.encode("utf-8")).hexdigest()
        if right_sig < left_sig:
            left_sig, right_sig = right_sig, left_sig
            left, right = right, left
''',
    '''        lang = "en" if str(language).lower() == "en" else "uk"
        left_sig = hashlib.sha256(f"{lang}\\0{left}".encode("utf-8")).hexdigest()
        right_sig = hashlib.sha256(f"{lang}\\0{right}".encode("utf-8")).hexdigest()
        if right_sig < left_sig:
            left_sig, right_sig = right_sig, left_sig
            left, right = right, left
''',
)
replace_once(
    "content_agent/database.py",
    '                    "en" if str(language).lower() == "en" else "uk", _iso(),\n',
    '                    lang, _iso(),\n',
)
replace_once(
    "content_agent/database.py",
    '        query = "SELECT id,group_id,title,source_text,active,created_at,updated_at FROM content_exclusions"\n',
    '        query = "SELECT id,group_id,signature,title,source_text,active,created_at,updated_at FROM content_exclusions"\n',
)

# Learning export/import must round-trip every exported connector, including the
# permanent inbox exclusion store.
replace_once(
    "content_agent/database.py",
    '''                for row in payload.get("learning_events", []):
                    if not isinstance(row, dict):
                        continue
''',
    '''                for row in payload.get("content_exclusions", []):
                    if not isinstance(row, dict):
                        continue
                    source_text = str(row.get("source_text") or "").strip()
                    if not source_text:
                        continue
                    signature = str(row.get("signature") or "").strip()
                    if not signature:
                        signature = sha256_bytes(source_text.casefold().encode("utf-8"))
                    cursor = db.execute(
                        """
                        INSERT INTO content_exclusions(
                            group_id,signature,title,source_text,active,created_at,updated_at
                        ) VALUES(?,?,?,?,?,?,?)
                        ON CONFLICT(signature) DO UPDATE SET
                            title=excluded.title,
                            source_text=excluded.source_text,
                            active=excluded.active,
                            updated_at=excluded.updated_at
                        """,
                        (
                            row.get("group_id"), signature, str(row.get("title") or ""), source_text,
                            1 if bool(row.get("active", True)) else 0,
                            str(row.get("created_at") or _iso()),
                            str(row.get("updated_at") or _iso()),
                        ),
                    )
                    counts["content_exclusions"] += int(bool(cursor.rowcount))
                for row in payload.get("learning_events", []):
                    if not isinstance(row, dict):
                        continue
''',
)

# Record explicit connector events for every user decision that should teach the
# local system. Plain deletion intentionally remains outside learning.
replace_once(
    "content_agent/ui/main_window.py",
    '''        self.db.forget_content_exclusion_for_group(group_id)
        self.load_group(group_id)
''',
    '''        forgotten = self.db.forget_content_exclusion_for_group(group_id)
        if forgotten and self.config.learning_enabled:
            self.db.record_learning_event(
                "exclusion_restored", language=self.config.ui_language, group_id=group_id,
                payload={"rules_deactivated": forgotten},
            )
        self.load_group(group_id)
''',
)
replace_once(
    "content_agent/ui/main_window.py",
    '''        try:
            remembered = self.db.remember_content_exclusions(group_ids)
        except Exception as exc:
''',
    '''        try:
            remembered = self.db.remember_content_exclusions(group_ids)
            if self.config.learning_enabled:
                for group_id in group_ids:
                    self.db.record_learning_event(
                        "content_excluded", language=self.config.ui_language, group_id=group_id,
                        payload={"selected_group_ids": group_ids},
                    )
        except Exception as exc:
''',
)
replace_once(
    "content_agent/ui/main_window.py",
    '''            learned_pairs = sum(
                1
                for source_group in groups[1:]
                if self.db.record_topic_feedback(
                    target.combined_text or target.canonical_title,
                    source_group.combined_text or source_group.canonical_title,
                    decision="merged",
                    language=self.config.ui_language,
                )
            )
        except Exception as exc:
''',
    '''            learned_pairs = sum(
                1
                for source_group in groups[1:]
                if self.db.record_topic_feedback(
                    target.combined_text or target.canonical_title,
                    source_group.combined_text or source_group.canonical_title,
                    decision="merged",
                    language=self.config.ui_language,
                )
            )
            if self.config.learning_enabled:
                self.db.record_learning_event(
                    "manual_groups_merged", language=self.config.ui_language,
                    group_id=target_group_id, anchor_group_id=target_group_id,
                    payload={"merged_group_ids": group_ids[1:], "moved_articles": moved_articles},
                )
        except Exception as exc:
''',
)
replace_once(
    "content_agent/ui/main_window.py",
    '''        if learned:
            self.editorial_memory_var.set(
''',
    '''        if self.config.learning_enabled:
            self.db.record_learning_event(
                "publication_approved", language=self.config.ui_language, group_id=group.id,
                payload={"batch_id": result.batch_id, "targets": sorted(targets), "example_added": learned},
            )
        if learned:
            self.editorial_memory_var.set(
''',
)

write(
    "tests/test_v1_1_learning_hardening.py",
    '''from __future__ import annotations

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
''',
)

Path(__file__).unlink()
print("v1.1.0 learning and migration hardening applied")
