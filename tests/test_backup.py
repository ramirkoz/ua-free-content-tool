from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from content_agent.backup import BackupError, create_backup, import_backup
from content_agent.config import AppConfig, save_config
from content_agent.database import Database
from content_agent.models import CollectedArticle
from content_agent.paths import config_path, database_path


def test_backup_and_import_roundtrip(isolated_data: Path) -> None:
    db = Database()
    source_id = db.add_source("rss", "one", "https://example.com/feed")
    db.insert_collected(source_id, [CollectedArticle("1", "title", "https://example.com/1", "body", None)], enforce_today=False)
    save_config(AppConfig(ollama_model="test-model", telegram_bot_token="123456:abcdefghijklmnopqrstuvwxyz"))
    backup = create_backup()

    db.add_source("rss", "two", "https://example.com/second")
    assert len(db.list_sources()) == 2
    result = import_backup(backup)
    restored = Database()
    assert len(restored.list_sources()) == 1
    assert result.safety_backup.exists()
    assert config_path().exists()


def test_backup_rejects_traversal(isolated_data: Path, tmp_path: Path) -> None:
    Database()
    malicious = tmp_path / "bad.zip"
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("../evil", b"x")
        archive.writestr("manifest.json", b"{}")
        archive.writestr("content_agent.sqlite3", b"not a db")
    with pytest.raises((BackupError, ValueError)):
        import_backup(malicious)


def test_backup_rejects_duplicate_names(isolated_data: Path, tmp_path: Path) -> None:
    Database()
    duplicate = tmp_path / "duplicate.zip"
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(duplicate, "w") as archive:
            archive.writestr("content_agent.sqlite3", b"first")
            archive.writestr("content_agent.sqlite3", b"second")
            archive.writestr("manifest.json", b"{}")
    with pytest.raises(BackupError, match="duplicate"):
        import_backup(duplicate)


def test_backup_rejects_oversized_entry(
    isolated_data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Database()
    monkeypatch.setattr("content_agent.backup._MAX_BACKUP_FILE_BYTES", 4)
    oversized = tmp_path / "oversized.zip"
    with zipfile.ZipFile(oversized, "w") as archive:
        archive.writestr("content_agent.sqlite3", b"12345")
        archive.writestr("manifest.json", b"{}")
    with pytest.raises(BackupError, match="too large"):
        import_backup(oversized)


def test_import_without_config_removes_current_config(isolated_data: Path) -> None:
    db = Database()
    source_id = db.add_source("rss", "one", "https://example.com/feed")
    db.insert_collected(source_id, [CollectedArticle("1", "title", "https://example.com/1", "body", None)], enforce_today=False)
    backup_without_config = create_backup()
    save_config(AppConfig(ollama_model="later-config"))
    assert config_path().exists()
    result = import_backup(backup_without_config)
    assert result.imported_config is False
    assert not config_path().exists()


def test_backup_rejects_wrong_database_schema(isolated_data: Path, tmp_path: Path) -> None:
    import hashlib
    import json
    import sqlite3

    Database()
    wrong_db = tmp_path / "wrong.sqlite3"
    connection = sqlite3.connect(wrong_db)
    try:
        connection.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY)")
        connection.execute("PRAGMA user_version=1")
        connection.commit()
    finally:
        connection.close()
    raw = wrong_db.read_bytes()
    manifest = {
        "application": "UA_FREE_Content_Tool",
        "schema": 2,
        "database_schema": 1,
        "created_at": "2026-07-24T00:00:00+00:00",
        "files": {
            "content_agent.sqlite3": {
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        },
    }
    archive_path = tmp_path / "wrong-schema.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("content_agent.sqlite3", raw)
        archive.writestr("manifest.json", json.dumps(manifest))
    with pytest.raises(BackupError, match="unsupported"):
        import_backup(archive_path)


def test_fsync_file_accepts_completed_writable_file(tmp_path: Path) -> None:
    from content_agent.backup import _fsync_file

    path = tmp_path / "completed.bin"
    path.write_bytes(b"durable")
    _fsync_file(path)
    assert path.read_bytes() == b"durable"
