from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import AppConfig
from ..v2.ai.gateway import AIGateway
from ..v2.publishing.registry import DestinationRegistry
from ..v2.storage.backup_contract import (
    backup_requires_password,
    create_backup,
    create_migration_backup,
    import_backup,
)
from ..v2.storage.factory import create_database
from ..v2.storage.reliable import Database


class BackupService:
    """Composition-owned entry point for durable backup/restore operations."""

    def create(self, destination_dir: Path | None = None) -> Path:
        return create_backup(destination_dir)

    def create_migration(self, password: str, destination_dir: Path | None = None) -> Path:
        return create_migration_backup(password, destination_dir)

    def requires_password(self, archive: Path) -> bool:
        return backup_requires_password(Path(archive))

    def restore(self, archive: Path, *, credential_password: str | None = None):
        return import_backup(Path(archive), credential_password=credential_password)


@dataclass(frozen=True, slots=True)
class AppServices:
    """Single runtime composition boundary for the active application.

    RC50 extends the RC47 composition root so UI no longer needs to rediscover
    destination identity or backup implementations through historical RC modules.
    """

    db: Database
    config: AppConfig
    ai: AIGateway
    destinations: DestinationRegistry
    backups: BackupService


def build_services(*, config: AppConfig, database: Database | None = None) -> AppServices:
    db = database if database is not None else create_database()
    return AppServices(
        db=db,
        config=config,
        ai=AIGateway(),
        destinations=DestinationRegistry(config),
        backups=BackupService(),
    )


__all__ = ["AppServices", "BackupService", "build_services"]
