from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ... import backup as legacy_backup
from ...maintenance import DATA_MAINTENANCE_LOCK
from ...paths import data_dir
from . import backup_contract

_PENDING_DIR_NAME = ".restore_pending_v3"
_PENDING_ARCHIVE_NAME = "backup.zip"
_PENDING_MARKER_NAME = "restore_pending.json"


@dataclass(frozen=True, slots=True)
class StagedRestore:
    archive: Path
    schema: int
    requires_password: bool
    safety_backup: Path


def _pending_dir() -> Path:
    return data_dir() / _PENDING_DIR_NAME


def _pending_archive() -> Path:
    return _pending_dir() / _PENDING_ARCHIVE_NAME


def _pending_marker() -> Path:
    return _pending_dir() / _PENDING_MARKER_NAME


def _schema(path: Path) -> int:
    manifest = backup_contract.peek_manifest(Path(path))
    try:
        return int(manifest.get("schema") or 0)
    except (TypeError, ValueError):
        return 0


def has_pending_restore() -> bool:
    return _pending_archive().is_file() and _pending_marker().is_file()


def pending_restore_requires_password() -> bool:
    if not has_pending_restore():
        return False
    try:
        marker = json.loads(_pending_marker().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return bool(isinstance(marker, dict) and marker.get("requires_password"))


def pending_restore_safety_backup() -> str:
    if not has_pending_restore():
        return ""
    try:
        marker = json.loads(_pending_marker().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ""
    return str(marker.get("safety_backup") or "") if isinstance(marker, dict) else ""


def _validate_for_stage(archive: Path, schema: int) -> None:
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="uafree-restore-stage-check-", dir=root) as temp_name:
        temp = Path(temp_name)
        if schema == backup_contract.SCHEMA:
            backup_contract._validate_archive(archive, temp)
            return
        if schema == 2:
            legacy_backup._validate_archive(archive, temp)
            return
        raise backup_contract.BackupContractError("Backup schema is unsupported.")


def stage_restore(archive_path: Path) -> StagedRestore:
    """Validate and stage a restore without replacing live runtime state.

    The current process keeps using its existing database. The archive is applied
    only by the next process before create_database() constructs any SQLite object.
    """

    archive = Path(archive_path)
    if not archive.is_file():
        raise backup_contract.BackupContractError("Backup file cannot be read.")
    schema = _schema(archive)
    _validate_for_stage(archive, schema)
    requires_password = schema == backup_contract.SCHEMA and backup_contract.backup_requires_password(archive)

    with DATA_MAINTENANCE_LOCK:
        safety = backup_contract.create_backup()
        root = data_dir()
        root.mkdir(parents=True, exist_ok=True)
        pending = _pending_dir()
        temp_pending = root / (_PENDING_DIR_NAME + ".tmp")
        if temp_pending.exists():
            shutil.rmtree(temp_pending)
        temp_pending.mkdir(parents=True, exist_ok=False)
        staged_archive = temp_pending / _PENDING_ARCHIVE_NAME
        shutil.copyfile(archive, staged_archive)
        marker = {
            "schema": "ua-free-content-tool-restore-pending-v1",
            "backup_schema": schema,
            "requires_password": requires_password,
            "safety_backup": str(safety),
        }
        (temp_pending / _PENDING_MARKER_NAME).write_text(
            json.dumps(marker, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        if pending.exists():
            shutil.rmtree(pending)
        temp_pending.replace(pending)
    return StagedRestore(
        archive=_pending_archive(),
        schema=schema,
        requires_password=requires_password,
        safety_backup=safety,
    )


def apply_pending_restore(*, credential_password: str | None = None):
    """Apply a staged restore before the active Database is constructed."""

    if not has_pending_restore():
        return None
    archive = _pending_archive()
    schema = _schema(archive)
    try:
        if schema == backup_contract.SCHEMA:
            result = backup_contract.import_backup(archive, credential_password=credential_password)
        elif schema == 2:
            result = legacy_backup.import_backup(archive)
        else:
            raise backup_contract.BackupContractError("Backup schema is unsupported.")
    except Exception:
        # Leave the staged archive intact so the operator can retry with the right
        # password or inspect the failure. Startup must fail closed rather than
        # silently continue on partially restored state.
        raise
    shutil.rmtree(_pending_dir(), ignore_errors=True)
    return result


__all__ = [
    "StagedRestore",
    "has_pending_restore",
    "pending_restore_requires_password",
    "pending_restore_safety_backup",
    "stage_restore",
    "apply_pending_restore",
]
