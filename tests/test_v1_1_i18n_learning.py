from __future__ import annotations

from pathlib import Path

from content_agent.config import AppConfig
from content_agent.database import DATABASE_SCHEMA_VERSION, Database
from content_agent.editorial_memory import EditorialExample, format_examples_for_prompt
from content_agent.i18n import language_from_label, tr
from content_agent.topic_search import build_topic_prompt


def test_config_supports_language_learning_and_independent_meta_apps() -> None:
    config = AppConfig(
        ui_language="en",
        learning_enabled=True,
        learning_examples_limit=5,
        facebook_app_id="fb",
        facebook_app_secret="fb-secret",
        threads_app_id="threads",
        threads_app_secret="threads-secret",
    )
    config.validate()
    restored = AppConfig.from_json_bytes(config.to_json_bytes())
    assert restored.ui_language == "en"
    assert restored.facebook_app_id == "fb"
    assert restored.threads_app_id == "threads"


def test_legacy_shared_meta_fields_migrate_to_both_apps() -> None:
    raw = AppConfig(meta_app_id="legacy", meta_app_secret="secret").to_json_bytes()
    restored = AppConfig.from_json_bytes(raw)
    assert restored.facebook_app_id == "legacy"
    assert restored.threads_app_id == "legacy"


def test_static_translation_and_language_label() -> None:
    assert tr("Вхідні", "en") == "Inbox"
    assert tr("Вхідні", "uk") == "Вхідні"
    assert language_from_label("English") == "en"


def test_editorial_prompt_examples_are_language_specific() -> None:
    example = EditorialExample(1, "source", "draft", "final", language="en", similarity=0.7)
    assert "EDITOR'S FINAL TEXT" in format_examples_for_prompt([example], language="en")
    assert "ФІНАЛЬНИЙ ТЕКСТ" in format_examples_for_prompt([example], language="uk")


def test_topic_prompt_uses_selected_language() -> None:
    prompt = build_topic_prompt(
        "Title", "Body", [{"group_id": 2, "title": "Candidate", "text": "Candidate body"}],
        language="en",
    )
    assert "ANCHOR STORY" in prompt
    assert "Return ONLY" in prompt


def test_schema_v8_and_learning_roundtrip(tmp_path: Path) -> None:
    assert DATABASE_SCHEMA_VERSION >= 8
    db = Database(tmp_path / "data.sqlite3")
    event_id = db.record_learning_event(
        "rewrite_generated", language="en", group_id=7, payload={"model": "test"}
    )
    rows = db.list_learning_events(language="en")
    assert rows[0]["id"] == event_id
    assert rows[0]["payload"] == {"model": "test"}
    exported = db.export_learning_data(tmp_path / "learning.json")
    assert exported.exists()
