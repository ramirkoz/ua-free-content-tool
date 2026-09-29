from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class Authenticator(Protocol):
    platform: str
    def ready(self, destination_key: str) -> bool: ...
    def state(self, destination_key: str) -> str: ...


class PublisherAdapter(Protocol):
    platform: str
    def supports(self, destination_key: str) -> bool: ...
    def create(self, destination_key: str): ...


@dataclass(slots=True)
class ConfigAuthenticator:
    config: object
    platform: str

    def ready(self, destination_key: str) -> bool:
        try:
            return bool(self.config.platform_ready(destination_key))
        except Exception:
            return False

    def state(self, destination_key: str) -> str:
        return "ready" if self.ready(destination_key) else "not_configured"


@dataclass(slots=True)
class FactoryPlatformAdapter:
    factory: object
    platform: str

    def supports(self, destination_key: str) -> bool:
        key = str(destination_key or "")
        base = key.split(":", 1)[0]
        return base == self.platform or (self.platform == "facebook" and key.startswith("facebook:"))

    def create(self, destination_key: str):
        if not self.supports(destination_key):
            raise ValueError(f"{self.platform} adapter cannot create {destination_key}")
        return self.factory.create(destination_key)


@dataclass(slots=True)
class GoogleDriveMediaAdapter:
    config: object
    platform: str = "google_drive"
    role: str = "media_source"

    def ready(self) -> bool:
        try:
            return bool(self.config.platform_ready("google_drive"))
        except Exception:
            return False


def build_authenticators(config) -> dict[str, ConfigAuthenticator]:
    return {
        name: ConfigAuthenticator(config, name)
        for name in ("telegram", "facebook", "instagram", "threads", "linkedin")
    }


def build_publisher_adapters(factory) -> dict[str, FactoryPlatformAdapter]:
    return {
        name: FactoryPlatformAdapter(factory, name)
        for name in ("telegram", "facebook", "instagram", "threads", "linkedin")
    }


__all__ = [
    "Authenticator",
    "PublisherAdapter",
    "ConfigAuthenticator",
    "FactoryPlatformAdapter",
    "GoogleDriveMediaAdapter",
    "build_authenticators",
    "build_publisher_adapters",
]
