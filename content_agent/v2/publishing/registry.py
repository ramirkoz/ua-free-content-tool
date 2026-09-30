from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Iterable

from ...destinations_v1_4 import DestinationSpec, destination_specs
from .contracts import AuthStatus, PlatformAdapter


@dataclass(frozen=True, slots=True)
class RegisteredDestination:
    key: str
    label: str
    platform: str
    auth: AuthStatus


class DestinationRegistry:
    """Single capability/auth-aware registry for publication destinations."""

    def __init__(self, config, adapters: Iterable[PlatformAdapter]) -> None:
        self.config = config
        self._lock = RLock()
        self._adapters = tuple(adapters)
        platforms = [adapter.platform for adapter in self._adapters]
        if len(platforms) != len(set(platforms)):
            raise ValueError("Кожна платформа може мати лише один активний RC52 adapter.")

    @property
    def adapters(self) -> tuple[PlatformAdapter, ...]:
        return self._adapters

    def adapter_for(self, target_key: str) -> PlatformAdapter:
        key = str(target_key or "").strip()
        matches = [adapter for adapter in self._adapters if adapter.matches(key)]
        if len(matches) != 1:
            raise KeyError(f"Для destination {key!r} очікувався рівно один platform adapter, знайдено {len(matches)}.")
        return matches[0]

    def specs(self) -> list[DestinationSpec]:
        with self._lock:
            return list(destination_specs(self.config))

    def destinations(self) -> list[RegisteredDestination]:
        with self._lock:
            rows: list[RegisteredDestination] = []
            for spec in destination_specs(self.config):
                adapter = self.adapter_for(spec.key)
                rows.append(
                    RegisteredDestination(
                        key=spec.key,
                        label=spec.label,
                        platform=spec.platform,
                        auth=adapter.auth_status(spec.key),
                    )
                )
            return rows

    def auth_status(self, target_key: str) -> AuthStatus:
        return self.adapter_for(target_key).auth_status(target_key)
