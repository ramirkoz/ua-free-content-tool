from __future__ import annotations

from pathlib import Path

from ... import backup as legacy_backup
from . import backup_contract


def _schema(path: Path) -> int:
    manifest = backup_contract.peek_manifest(Path(path))
    try:
        return int(manifest.get("schema") or 0)
    except (TypeError, ValueError):
        return 0


def create_backup(destination_dir: Path | None = None) -> Path:
    """Create the credential-free durable backup."""
    return backup_contract.create_backup(destination_dir)


def create_migration_backup(password: str, destination_dir: Path | None = None) -> Path:
    """Create an explicit password-protected cross-machine credential migration."""
    return backup_contract.create_migration_backup(password, destination_dir)


def backup_requires_password(path: Path) -> bool:
    return backup_contract.backup_requires_password(Path(path))


def import_backup(path: Path, *, credential_password: str | None = None):
    """Import current schema or historical schema 2 backups."""
    archive = Path(path)
    schema = _schema(archive)
    if schema == backup_contract.SCHEMA:
        return backup_contract.import_backup(archive, credential_password=credential_password)
    if schema == 2:
        return legacy_backup.import_backup(archive)
    raise backup_contract.BackupContractError("Backup schema is unsupported.")


class BackupService:
    """Small composition-root facade over the fail-closed backup contract."""

    def create(self, destination_dir: Path | None = None) -> Path:
        return create_backup(destination_dir)

    def create_migration(self, password: str, destination_dir: Path | None = None) -> Path:
        return create_migration_backup(password, destination_dir)

    def requires_password(self, path: Path) -> bool:
        return backup_requires_password(path)

    def restore(self, path: Path, *, credential_password: str | None = None):
        return import_backup(path, credential_password=credential_password)


__all__ = [
    "BackupService",
    "create_backup",
    "create_migration_backup",
    "backup_requires_password",
    "import_backup",
]
