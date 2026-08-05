from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from content_agent.config import AppConfig, ConfigError, load_config, save_config
from content_agent.database import Database
from content_agent.paths import (
    config_path,
    data_dir,
    database_path,
    portable_key_path,
    portable_mode,
    reset_path_cache_for_tests,
)
from content_agent.portable import ensure_portable_data_migrated


def _portable_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str = "Portable App") -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "portable.flag").write_text("", encoding="utf-8")
    monkeypatch.delenv("UA_FREE_CONTENT_DATA", raising=False)
    monkeypatch.setenv("UA_FREE_PORTABLE_ROOT", str(root))
    reset_path_cache_for_tests()
    return root


def test_portable_mode_uses_data_beside_exe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _portable_root(tmp_path, monkeypatch)
    assert portable_mode()
    assert data_dir() == root / "Data"
    assert database_path() == root / "Data" / "content_agent.sqlite3"
    assert config_path() == root / "Data" / "config.portable"
    assert portable_key_path() == root / "Data" / "portable.key"


def test_portable_settings_survive_copy_to_another_computer_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _portable_root(tmp_path, monkeypatch, "Computer One")
    original = AppConfig(
        threads_token="THREADS_TEST_SECRET",
        telegram_bot_token="TELEGRAM_TEST_SECRET",
        telegram_chat_id="@uafree_org",
        google_client_id="123.apps.googleusercontent.com",
        google_client_secret="GOOGLE_SECRET",
        google_refresh_token="GOOGLE_REFRESH",
        ui_font_size=18,
    )
    save_config(original)
    assert config_path().exists() and portable_key_path().exists()
    assert b"THREADS_TEST_SECRET" not in config_path().read_bytes()

    copied = tmp_path / "Computer Two"
    shutil.copytree(root, copied)
    monkeypatch.setenv("UA_FREE_PORTABLE_ROOT", str(copied))
    reset_path_cache_for_tests()
    loaded = load_config()
    assert loaded.threads_token == original.threads_token
    assert loaded.telegram_bot_token == original.telegram_bot_token
    assert loaded.google_refresh_token == original.google_refresh_token
    assert loaded.ui_font_size == 18


def test_portable_config_missing_key_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _portable_root(tmp_path, monkeypatch)
    save_config(AppConfig(threads_token="secret"))
    portable_key_path().unlink()
    with pytest.raises(ConfigError, match="key is missing"):
        load_config()


def test_first_portable_run_imports_old_local_data_without_deleting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _portable_root(tmp_path, monkeypatch)
    old = tmp_path / "Old LocalAppData" / "data"
    old.mkdir(parents=True)
    monkeypatch.setenv("UA_FREE_LEGACY_DATA_ROOT", str(old))
    monkeypatch.setenv("UA_FREE_TEST_PLAINTEXT_CONFIG", "1")

    old_config = AppConfig(
        threads_token="OLD_THREADS_TOKEN",
        linkedin_token="OLD_LINKEDIN_TOKEN",
        telegram_bot_token="OLD_TELEGRAM_TOKEN",
        telegram_chat_id="@old_channel",
        google_client_id="123.apps.googleusercontent.com",
        google_client_secret="OLD_GOOGLE_SECRET",
        google_refresh_token="OLD_GOOGLE_REFRESH",
    )
    save_config(old_config, old / "config.dpapi")
    old_db = Database(old / "content_agent.sqlite3")
    old_db.add_source("rss", "Old source", "https://example.com/feed")

    result = ensure_portable_data_migrated()
    assert result.migrated and result.database_migrated and result.config_migrated
    assert (root / "Data" / "portable-migration.json").exists()
    assert (old / "config.dpapi").exists() and (old / "content_agent.sqlite3").exists()
    assert load_config().threads_token == "OLD_THREADS_TOKEN"
    assert load_config().google_refresh_token == "OLD_GOOGLE_REFRESH"
    assert Database().list_sources()[0].name == "Old source"

    # A second start must trust the portable data and never overwrite it again.
    assert not ensure_portable_data_migrated().migrated


def test_portable_backup_keeps_encrypted_config_and_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zipfile

    from content_agent.backup import create_backup, import_backup

    _portable_root(tmp_path, monkeypatch)
    db = Database()
    db.add_source("rss", "Portable source", "https://example.com/portable")
    save_config(AppConfig(threads_token="PORTABLE_TOKEN", ui_font_size=20))
    backup = create_backup()
    with zipfile.ZipFile(backup) as archive:
        assert set(archive.namelist()) == {
            "content_agent.sqlite3",
            "config.portable",
            "portable.key",
            "manifest.json",
        }

    save_config(AppConfig(threads_token="CHANGED", ui_font_size=9))
    Database().add_source("rss", "Extra", "https://example.com/extra")
    import_backup(backup)
    restored = load_config()
    assert restored.threads_token == "PORTABLE_TOKEN"
    assert restored.ui_font_size == 20
    assert [item.name for item in Database().list_sources()] == ["Portable source"]


def test_windows_build_marks_release_as_portable_and_versioned() -> None:
    root = Path(__file__).resolve().parents[1]
    batch = (root / "Build_Portable_Windows.bat").read_text(encoding="utf-8-sig")
    builder = (root / "tools" / "build_signed_python_runtime.ps1").read_text(encoding="utf-8")

    assert "PUBLIC_VERSION.txt" in batch
    assert "UA_FREE_Content_Tool_v%PUBLIC_VERSION%" in batch
    assert "portable.flag" in builder
    assert "clean_start.flag" in builder
    assert 'Join-Path $appRoot "Data"' in builder
    assert "PORTABLE_MODE.md" in builder
    assert "UA_FREE_Content_Tool.exe" in builder
    assert "Python Software Foundation" in builder
