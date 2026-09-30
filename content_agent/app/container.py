from __future__ import annotations

from dataclasses import dataclass

from ..config import AppConfig
from ..services.maintenance import MaintenanceService
from ..v2.ai.gateway import AIGateway
from ..v2.storage.factory import create_database
from ..v2.storage.reliable import Database


@dataclass(frozen=True, slots=True)
class AppServices:
    """Single runtime composition boundary for the active application.

    Storage/maintenance and the canonical AI gateway are assembled here. Publishing
    and destination adapters remain the explicit RC52 milestone.
    """

    db: Database
    config: AppConfig
    ai: AIGateway
    maintenance: MaintenanceService


def build_services(*, config: AppConfig, database: Database | None = None) -> AppServices:
    db = database if database is not None else create_database()
    return AppServices(
        db=db,
        config=config,
        ai=AIGateway(),
        maintenance=MaintenanceService(),
    )


__all__ = ["AppServices", "build_services"]
