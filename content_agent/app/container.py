from __future__ import annotations

from dataclasses import dataclass

from ..config import AppConfig
from ..services.maintenance import MaintenanceService
from ..v2.ai.gateway import AIGateway
from ..v2.publishing.media import GoogleDriveMediaService
from ..v2.publishing.registry import DestinationRegistry
from ..v2.publishing.runtime import build_destination_registry
from ..v2.publishing.service import PublicationService
from ..v2.storage.factory import create_database
from ..v2.storage.reliable import Database


@dataclass(frozen=True, slots=True)
class AppServices:
    """Single runtime composition boundary for the active application."""

    db: Database
    config: AppConfig
    ai: AIGateway
    maintenance: MaintenanceService
    destinations: DestinationRegistry
    publishing: PublicationService
    media: GoogleDriveMediaService


def build_services(*, config: AppConfig, database: Database | None = None) -> AppServices:
    db = database if database is not None else create_database()
    destinations = build_destination_registry(config)
    publishing = PublicationService(destinations)
    return AppServices(
        db=db,
        config=config,
        ai=AIGateway(),
        maintenance=MaintenanceService(),
        destinations=destinations,
        publishing=publishing,
        media=GoogleDriveMediaService(config),
    )


__all__ = ["AppServices", "build_services"]
