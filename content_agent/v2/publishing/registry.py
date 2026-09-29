from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from ...destinations_v1_4 import destination_specs, load_instagram_catalog, load_telegram_catalog


@dataclass(frozen=True, slots=True)
class DestinationDescriptor:
    key: str
    label: str
    platform: str
    role: str = "publisher"
    configured: bool = False
    auth_state: str = "not_configured"


class PublisherAdapter(Protocol):
    key: str
    def publish(self, *args, **kwargs): ...


class Authenticator(Protocol):
    key: str
    def status(self) -> str: ...


class DestinationRegistry:
    """Stable registry of operator-visible destinations and capabilities."""

    def __init__(self, config) -> None:
        self.config = config

    def descriptors(self) -> tuple[DestinationDescriptor, ...]:
        result: list[DestinationDescriptor] = []
        seen: set[str] = set()
        try:
            specs: Iterable[object] = destination_specs(self.config)
        except Exception:
            specs = ()
        for spec in specs:
            key = str(getattr(spec, "key", "") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            platform = str(getattr(spec, "platform", key.split(":", 1)[0]) or "")
            try:
                ready = bool(self.config.platform_ready(key))
            except Exception:
                ready = False
            result.append(DestinationDescriptor(
                key=key,
                label=str(getattr(spec, "label", key) or key),
                platform=platform,
                configured=ready,
                auth_state="ready" if ready else "not_configured",
            ))
        try:
            for row in load_instagram_catalog():
                key = str(row.key)
                if key in seen:
                    continue
                seen.add(key)
                ready = bool(self.config.platform_ready(key))
                result.append(DestinationDescriptor(key, row.label, "instagram", configured=ready, auth_state="ready" if ready else "not_configured"))
        except Exception:
            pass
        try:
            for row in load_telegram_catalog():
                key = str(row.key)
                if key in seen:
                    continue
                seen.add(key)
                ready = bool(self.config.platform_ready(key))
                result.append(DestinationDescriptor(key, row.label, "telegram", configured=ready, auth_state="ready" if ready else "not_configured"))
        except Exception:
            pass
        try:
            drive_ready = bool(self.config.platform_ready("google_drive"))
        except Exception:
            drive_ready = False
        result.append(DestinationDescriptor(
            key="google_drive",
            label="Google Drive (медіа)",
            platform="google_drive",
            role="media_source",
            configured=drive_ready,
            auth_state="ready" if drive_ready else "not_configured",
        ))
        return tuple(result)

    def publishers(self) -> tuple[DestinationDescriptor, ...]:
        return tuple(item for item in self.descriptors() if item.role == "publisher")

    def media_sources(self) -> tuple[DestinationDescriptor, ...]:
        return tuple(item for item in self.descriptors() if item.role == "media_source")

    def by_key(self, key: str) -> DestinationDescriptor | None:
        token = str(key or "").strip()
        return next((item for item in self.descriptors() if item.key == token), None)
