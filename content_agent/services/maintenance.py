from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..v2.storage import backup_api
from ..v2.storage.restore_pending import StagedRestore, stage_restore


@dataclass(frozen=True, slots=True)
class MaintenanceService:
    """Application boundary for backup and restore operations.

    UI code calls this service instead of importing the storage implementation
    directly. Restore is staged and becomes active only on the next process start.
    """

    def create_backup(self, destination_dir: Path | None = None) -> Path:
        return backup_api.create_backup(destination_dir)

    def create_migration_backup(self, password: str, destination_dir: Path | None = None) -> Path:
        return backup_api.create_migration_backup(password, destination_dir)

    def stage_restore(
        self,
        archive_path: Path,
        *,
        credential_password: str | None = None,
    ) -> StagedRestore:
        return stage_restore(Path(archive_path), credential_password=credential_password)

    def backup_requires_password(self, archive_path: Path) -> bool:
        return backup_api.backup_requires_password(Path(archive_path))


__all__ = ["MaintenanceService"]
