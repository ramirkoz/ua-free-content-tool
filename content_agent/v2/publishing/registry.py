from __future__ import annotations

from dataclasses import dataclass

from ...destinations_v1_4 import DestinationSpec, destination_ready, destination_specs


@dataclass(frozen=True, slots=True)
class DestinationState:
    key: str
    label: str
    platform: str
    ready: bool
    kind: str = "publisher"


class DestinationRegistry:
    """Canonical V2 destination identity/readiness registry.

    Authentication remains owned by the platform-specific configuration/adapters;
    this registry gives UI, queue and services one authoritative way to enumerate
    destination IDs and readiness. Google Drive is deliberately not a publisher.
    """

    def __init__(self, config) -> None:
        self.config = config

    def specs(self) -> list[DestinationSpec]:
        return list(destination_specs(self.config))

    def states(self) -> list[DestinationState]:
        return [
            DestinationState(row.key, row.label, row.platform, bool(destination_ready(self.config, row.key)))
            for row in self.specs()
        ]

    def state(self, key: str) -> DestinationState | None:
        wanted = str(key or "").strip()
        return next((row for row in self.states() if row.key == wanted), None)

    def ready(self, key: str) -> bool:
        row = self.state(key)
        return bool(row and row.ready)

    def labels(self) -> dict[str, str]:
        return {row.key: row.label for row in self.states()}

    def platform_keys(self, platform: str) -> tuple[str, ...]:
        wanted = str(platform or "").strip().casefold()
        return tuple(row.key for row in self.states() if row.platform.casefold() == wanted)


__all__ = ["DestinationRegistry", "DestinationState"]
