from __future__ import annotations

from pathlib import Path

from content_agent.i18n import LocalizedFileDialog, LocalizedMessageBox, tr
from content_agent.queue_migration import build_queue_compression_prompt


def test_secondary_ui_catalog_is_complete_for_known_dialogs() -> None:
    assert tr("Діагностика підключень", "en") == "Connection diagnostics"
    assert tr("Переробити всі через Ollama", "en") == "Rewrite all with Ollama"
    assert tr("Об’єднання завершено", "en") == "Merge completed"


def test_dynamic_translation_patterns_cover_operation_and_queue_text() -> None:
    assert tr("Виконується 01:23. Не закривайте програму.", "en") == "Running 01:23. Do not close the application."
    assert tr("Оброблено 2/5: пакет #18.", "en") == "Processed 2/5: batch #18."


def test_queue_compression_prompt_follows_application_language() -> None:
    english = build_queue_compression_prompt("Source text", 900, language="en")
    ukrainian = build_queue_compression_prompt("Текст", 900, language="uk")
    assert "ENGLISH ONLY" in english
    assert "APPROVED TEXT" in english
    assert "повністю українською" in ukrainian


def test_dialog_proxies_are_available_to_both_windows() -> None:
    assert LocalizedMessageBox
    assert LocalizedFileDialog
    main = (Path(__file__).parents[1] / "content_agent" / "ui" / "main_window.py").read_text(encoding="utf-8")
    queue = (Path(__file__).parents[1] / "content_agent" / "ui" / "queue_migration_dialog.py").read_text(encoding="utf-8")
    assert "self.msg = LocalizedMessageBox" in main
    assert "self.files = LocalizedFileDialog" in main
    assert "self.msg = LocalizedMessageBox" in queue
