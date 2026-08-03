from __future__ import annotations

from pathlib import Path

import pytest

from content_agent.config import AppConfig, load_config, save_config
from content_agent.database import Database
from content_agent.paths import reset_path_cache_for_tests
from content_agent.portable import ensure_portable_data_migrated


def _portable_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "portable.flag").write_text("", encoding="utf-8")
    monkeypatch.delenv("UA_FREE_CONTENT_DATA", raising=False)
    monkeypatch.setenv("UA_FREE_PORTABLE_ROOT", str(root))
    reset_path_cache_for_tests()
    return root


def test_empty_runner_database_does_not_block_real_legacy_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _portable_root(tmp_path, monkeypatch, "Gate-built portable")
    old = tmp_path / "Real LocalAppData" / "data"
    old.mkdir(parents=True)
    monkeypatch.setenv("UA_FREE_LEGACY_DATA_ROOT", str(old))
    monkeypatch.setenv("UA_FREE_TEST_PLAINTEXT_CONFIG", "1")

    old_db = Database(old / "content_agent.sqlite3")
    old_db.add_source("telegram", "Real source", "https://t.me/real_source")
    save_config(
        AppConfig(
            threads_token="REAL_THREADS_TOKEN",
            telegram_bot_token="REAL_TELEGRAM_TOKEN",
            telegram_chat_id="@real_channel",
            google_client_id="123.apps.googleusercontent.com",
            google_refresh_token="REAL_GOOGLE_REFRESH",
            ui_font_size=18,
        ),
        old / "config.dpapi",
    )

    # The Windows runner starts the built EXE once. Database() creates a valid
    # schema-only DB in Data, which FIX6 incorrectly treated as authoritative.
    empty_portable_db = Database(root / "Data" / "content_agent.sqlite3")
    assert empty_portable_db.list_sources() == []

    result = ensure_portable_data_migrated()
    assert result.migrated
    assert result.database_migrated
    assert result.config_migrated
    assert [item.name for item in Database().list_sources()] == ["Real source"]
    loaded = load_config()
    assert loaded.threads_token == "REAL_THREADS_TOKEN"
    assert loaded.google_refresh_token == "REAL_GOOGLE_REFRESH"
    assert loaded.ui_font_size == 18


def test_existing_portable_user_database_is_preserved_while_missing_config_is_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _portable_root(tmp_path, monkeypatch, "Portable with user data")
    old = tmp_path / "Legacy" / "data"
    old.mkdir(parents=True)
    monkeypatch.setenv("UA_FREE_LEGACY_DATA_ROOT", str(old))
    monkeypatch.setenv("UA_FREE_TEST_PLAINTEXT_CONFIG", "1")

    portable_db = Database(root / "Data" / "content_agent.sqlite3")
    portable_db.add_source("rss", "Keep portable", "https://portable.example/feed")
    legacy_db = Database(old / "content_agent.sqlite3")
    legacy_db.add_source("rss", "Do not overwrite", "https://legacy.example/feed")
    save_config(AppConfig(threads_token="LEGACY_TOKEN"), old / "config.dpapi")

    result = ensure_portable_data_migrated()
    assert result.migrated
    assert not result.database_migrated
    assert result.config_migrated
    assert [item.name for item in Database().list_sources()] == ["Keep portable"]
    assert load_config().threads_token == "LEGACY_TOKEN"


def test_default_portable_config_created_by_empty_ui_can_be_recovered_from_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _portable_root(tmp_path, monkeypatch, "Portable default config")
    old = tmp_path / "Legacy" / "data"
    old.mkdir(parents=True)
    monkeypatch.setenv("UA_FREE_LEGACY_DATA_ROOT", str(old))
    monkeypatch.setenv("UA_FREE_TEST_PLAINTEXT_CONFIG", "1")

    save_config(AppConfig())
    save_config(
        AppConfig(threads_token="RECOVERED_TOKEN", ui_font_size=19),
        old / "config.dpapi",
    )

    result = ensure_portable_data_migrated()
    assert result.migrated and result.config_migrated
    loaded = load_config()
    assert loaded.threads_token == "RECOVERED_TOKEN"
    assert loaded.ui_font_size == 19
