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

    RC50 keeps concrete legacy publishing/editorial implementations behind their
    existing boundaries for the later RC51/RC52 work, but storage and maintenance
    are now composed explicitly here instead of being selected by the UI.
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
