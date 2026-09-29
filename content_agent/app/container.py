from __future__ import annotations

from dataclasses import dataclass

from ..config import AppConfig
from ..v2.ai.gateway import AIGateway
from ..v2.storage.factory import create_database
from ..v2.storage.reliable import Database


@dataclass(frozen=True, slots=True)
class AppServices:
    """Single runtime composition boundary for the active application.

    RC47 intentionally starts small: the active database, configuration and AI
    gateway are composed here. Legacy UI layers still receive the concrete objects
    they already understand, but they no longer decide which database composition
    or AI entry point is authoritative.
    """

    db: Database
    config: AppConfig
    ai: AIGateway


def build_services(*, config: AppConfig, database: Database | None = None) -> AppServices:
    db = database if database is not None else create_database()
    return AppServices(db=db, config=config, ai=AIGateway())


__all__ = ["AppServices", "build_services"]
