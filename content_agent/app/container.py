from __future__ import annotations

from dataclasses import dataclass

from ..config import AppConfig
from ..v2.ai.gateway import AIGateway
from ..v2.collection import CollectionService
from ..v2.publishing.destinations import DestinationRegistry
from ..v2.storage.backup_api import BackupAPI
from ..v2.storage.factory import create_database
from ..v2.storage.reliable import Database


@dataclass(frozen=True, slots=True)
class AppServices:
    """Single runtime composition boundary for active application services."""

    db: Database
    config: AppConfig
    ai: AIGateway
    collection: CollectionService
    destinations: DestinationRegistry
    backups: BackupAPI

    def __getattr__(self, name: str):
        """Temporary compatibility bridge for legacy UI expecting database methods.

        New code should use ``services.db`` explicitly. The bridge keeps the active
        application on one composition root while thin historical UI layers are
        collapsed without changing behavior in one risky step.
        """
        return getattr(self.db, name)


def build_services(*, config: AppConfig, database: Database | None = None) -> AppServices:
    db = database if database is not None else create_database()
    return AppServices(
        db=db,
        config=config,
        ai=AIGateway(),
        collection=CollectionService(),
        destinations=DestinationRegistry(config),
        backups=BackupAPI(db),
    )


__all__ = ["AppServices", "build_services"]
