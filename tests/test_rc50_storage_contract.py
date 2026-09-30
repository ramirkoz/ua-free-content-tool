from __future__ import annotations

import inspect
import json
import zipfile
from pathlib import Path

import pytest

from content_agent.app.container import build_services
from content_agent.config import AppConfig
from content_agent.database import Database as LegacyDatabase
from content_agent.services.maintenance import MaintenanceService
from content_agent.v2.storage import backup_contract
from content_agent.v2.storage.factory import create_database
from content_agent.v2.storage.manual_topics import ManualTopicsMixin
from content_agent.v2.storage import restore_pending
from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow


def _patch_backup_paths(monkeypatch: pytest.MonkeyPatch, root: Path) -> Path:
    data = root / "Data"
    data.mkdir(parents=True, exist_ok=True)
    backups = data / "Backups"
    db_path = data / "content_agent.sqlite3"
    monkeypatch.setattr(backup_contract, "data_dir", lambda: data)
    monkeypatch.setattr(backup_contract, "backups_dir", lambda: backups)
    monkeypatch.setattr(backup_contract, "database_path", lambda: db_path)
    monkeypatch.setattr(restore_pending, "data_dir", lambda: data)
    return db_path


def test_rc50_manual_topics_schema_is_owned_by_numbered_migration(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    legacy = LegacyDatabase(path)
    source_id = legacy.add_source("rss", "Legacy", "https://example.test/feed")
    with legacy.connect() as db:
        assert "topic_id" not in {str(row[1]) for row in db.execute("PRAGMA table_info(sources)")}

    active = create_database(path)
    with active.connect() as db:
        columns = {str(row[1]) for row in db.execute("PRAGMA table_info(sources)")}
        migrations = {str(row[0]) for row in db.execute("SELECT id FROM schema_migrations")}
        source = db.execute("SELECT name FROM sources WHERE id=?", (source_id,)).fetchone()
    assert "topic_id" in columns
    assert "0008_manual_topics" in migrations
    assert source[0] == "Legacy"


def test_rc50_manual_topics_mixin_no_longer_mutates_schema_from_constructor() -> None:
    source = inspect.getsource(ManualTopicsMixin)
    assert "def __init__" not in source
    assert "ALTER TABLE" not in source
    assert "CREATE TABLE" not in source


def test_rc50_composition_root_owns_maintenance_service(tmp_path: Path) -> None:
    services = build_services(config=AppConfig(), database=create_database(tmp_path / "app.sqlite3"))
    assert isinstance(services.maintenance, MaintenanceService)
    assert callable(services.maintenance.create_backup)
    assert callable(services.maintenance.create_migration_backup)
    assert callable(services.maintenance.stage_restore)


def test_rc50_normal_backup_contains_durable_state_but_no_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = _patch_backup_paths(monkeypatch, tmp_path)
    create_database(db_path)
    data = db_path.parent
    (data / "instagram_destinations_v1_4.json").write_text(
        json.dumps({"accounts": [{"id": "one"}]}), encoding="utf-8"
    )
    (data / "ai_providers.secure").write_text("must-not-be-in-normal-backup", encoding="utf-8")

    archive = backup_contract.create_backup()
    with zipfile.ZipFile(archive, "r") as handle:
        names = set(handle.namelist())
        durable = json.loads(handle.read("durable_state.json").decode("utf-8"))
        manifest = json.loads(handle.read("manifest.json").decode("utf-8"))

    assert names == {
        "content_agent.sqlite3",
        "durable_state.json",
        "publication_receipts.json",
        "manifest.json",
    }
    assert "credentials.enc" not in names
    assert "ai_providers.secure" not in names
    assert durable["instagram_destinations_v1_4.json"]["accounts"][0]["id"] == "one"
    assert manifest["mode"] == "normal"
    assert manifest["credential_protection"] == "none"


def test_rc50_migration_backup_password_is_validated_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = _patch_backup_paths(monkeypatch, tmp_path)
    create_database(db_path)
    payload = {
        "schema": "ua-free-content-tool-credential-migration-v1",
        "app_config": {},
        "ai_provider_secrets": {},
        "openrouter_api_key": "",
    }
    monkeypatch.setattr(
        backup_contract,
        "_credential_payload",
        lambda: json.dumps(payload, sort_keys=True).encode("utf-8"),
    )
    archive = backup_contract.create_migration_backup("correct-password")

    with pytest.raises(backup_contract.BackupContractError):
        restore_pending.stage_restore(archive, credential_password="wrong-password")
    assert not restore_pending.has_pending_restore()

    staged = restore_pending.stage_restore(archive, credential_password="correct-password")
    assert staged.requires_password is True
    assert restore_pending.has_pending_restore()
    assert restore_pending.pending_restore_requires_password() is True
    with zipfile.ZipFile(staged.archive, "r") as handle:
        assert "credentials.enc" in handle.namelist()


def test_rc50_active_window_uses_composed_maintenance_boundary() -> None:
    source = inspect.getsource(MainWindow)
    assert "self.services.maintenance.create_backup" in source
    assert "self.services.maintenance.create_migration_backup" in source
    assert "self.services.maintenance.stage_restore" in source
    assert "from ...backup import import_backup" not in source


def test_rc50_adds_no_new_versioned_mainwindow_layer() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    forbidden = [
        path.relative_to(repo_root).as_posix()
        for path in (repo_root / "content_agent").rglob("*.py")
        if "window_rc50" in path.name.casefold()
    ]
    assert forbidden == []
