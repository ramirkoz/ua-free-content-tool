from __future__ import annotations

from pathlib import Path

from content_agent.config import AppConfig, save_config
from content_agent.database import Database
from content_agent.paths import reset_path_cache_for_tests
from content_agent.portable import ensure_portable_data_migrated


def test_fix25_clean_start_marker_blocks_legacy_auto_import(tmp_path: Path, monkeypatch) -> None:
    portable_root = tmp_path / "portable"
    portable_root.mkdir()
    (portable_root / "portable.flag").write_text("", encoding="utf-8")
    (portable_root / "clean_start.flag").write_text("", encoding="utf-8")

    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    monkeypatch.setenv("UA_FREE_PORTABLE_ROOT", str(portable_root))
    monkeypatch.setenv("UA_FREE_LEGACY_DATA_ROOT", str(legacy_root))
    monkeypatch.setenv("UA_FREE_TEST_PLAINTEXT_CONFIG", "1")
    monkeypatch.delenv("UA_FREE_CONTENT_DATA", raising=False)
    reset_path_cache_for_tests()

    old_db = Database(path=legacy_root / "content_agent.sqlite3")
    old_db.add_source("telegram", "Old channel", "@old_channel")
    save_config(
        AppConfig(
            telegram_bot_token="123456:abcdefghijklmnopqrstuvwxyz",
            telegram_chat_id="@old_channel",
            linkedin_author_urn="urn:li:person:123",
            linkedin_token="old-linkedin-token",
        ),
        legacy_root / "config.dpapi",
    )

    result = ensure_portable_data_migrated()

    assert not result.migrated
    assert not (portable_root / "Data" / "content_agent.sqlite3").exists()
    assert not (portable_root / "Data" / "config.portable").exists()
    reset_path_cache_for_tests()


def test_fix25_settings_layout_keeps_form_width_and_actions_inside_rows() -> None:
    source = Path("content_agent/ui/main_window.py").read_text(encoding="utf-8")

    assert "form_window = canvas.create_window" in source
    assert "canvas.itemconfigure(form_window, width=max(1, event.width))" in source
    assert "meta_actions = ttk.Frame(meta)" in source
    assert "threads_actions = ttk.Frame(threads)" in source
    assert "linkedin_actions = ttk.Frame(linkedin)" in source
    assert "telegram_actions = ttk.Frame(telegram)" in source
    assert "google_actions = ttk.Frame(google)" in source
    assert "action_buttons = ttk.Frame(actions)" in source


def test_fix25_portable_build_marks_fresh_copies_as_clean_start() -> None:
    build = Path("Build_Portable_Windows.bat").read_text(encoding="utf-8")

    assert 'type nul > "%APP_FOLDER%\\clean_start.flag"' in build
    assert 'set "TARGET=Release\\UA_FREE_Content_Tool_R8_FIX30"' in build
