from __future__ import annotations

from dataclasses import dataclass

from ..config import AppConfig
from ..v2.ai.gateway import AIGateway
from ..v2.publishing.registry import DestinationRegistry
from ..v2.services import CollectionService, MaintenanceService, PublishingService
from ..v2.storage.factory import create_database
from ..v2.storage.reliable import Database


@dataclass(frozen=True, slots=True)
class AppServices:
    """Single concrete composition root for the active V2 application.

    UI layers receive this object instead of choosing concrete database, AI,
    collection, publishing or maintenance implementations themselves. Legacy UI
    remains a compatibility host while active behavior is composed here.
    """

    db: Database
    config: AppConfig
    ai: AIGateway
    destinations: DestinationRegistry
    collection: CollectionService
    publishing: PublishingService
    maintenance: MaintenanceService


def build_services(*, config: AppConfig, database: Database | None = None) -> AppServices:
    db = database if database is not None else create_database()
    destinations = DestinationRegistry(config)
    return AppServices(
        db=db,
        config=config,
        ai=AIGateway(),
        destinations=destinations,
        collection=CollectionService(),
        publishing=PublishingService(config, destinations),
        maintenance=MaintenanceService(),
    )


__all__ = ["AppServices", "build_services"]
