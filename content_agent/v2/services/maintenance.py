from __future__ import annotations

from pathlib import Path

from ..storage import backup_api


class MaintenanceService:
    """Durable maintenance boundary for backup/restore/migration operations."""

    def create_backup(self, destination_dir: Path | None = None) -> Path:
        return backup_api.create_backup(destination_dir)

    def create_migration_backup(self, password: str, destination_dir: Path | None = None) -> Path:
        return backup_api.create_migration_backup(password, destination_dir)

    def backup_requires_password(self, path: Path) -> bool:
        return backup_api.backup_requires_password(path)

    def import_backup(self, path: Path, *, credential_password: str | None = None):
        return backup_api.import_backup(path, credential_password=credential_password)
