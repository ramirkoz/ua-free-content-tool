from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Iterable

from .contracts import PlatformAdapter


class DestinationError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class DestinationEntry:
    family: str
    adapter: PlatformAdapter


class DestinationRegistry:
    """Single registry for publication destinations.

    Google Drive is intentionally rejected here: it is a media/storage service,
    never a publication destination.
    """

    def __init__(self, adapters: Iterable[PlatformAdapter] = ()) -> None:
        self._lock = RLock()
        self._adapters: dict[str, PlatformAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: PlatformAdapter) -> None:
        family = str(adapter.family or "").strip().casefold()
        if not family:
            raise ValueError("Platform adapter family is required.")
        if family in {"google_drive", "drive", "gdrive"}:
            raise ValueError("Google Drive is a media service, not a publisher.")
        with self._lock:
            if family in self._adapters:
                raise ValueError(f"Platform adapter already registered: {family}")
            self._adapters[family] = adapter

    @staticmethod
    def family_for(destination: str) -> str:
        key = str(destination or "").strip().casefold()
        if not key:
            raise DestinationError("Destination is empty.")
        return key.split(":", 1)[0]

    def resolve(self, destination: str) -> DestinationEntry:
        family = self.family_for(destination)
        if family in {"google_drive", "drive", "gdrive"}:
            raise DestinationError("Google Drive is a media/storage service and cannot publish posts.")
        with self._lock:
            adapter = self._adapters.get(family)
        if adapter is None or not adapter.matches(destination):
            raise DestinationError(f"Unsupported publication destination: {destination}")
        return DestinationEntry(family=family, adapter=adapter)

    def families(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._adapters))

    def adapters(self) -> tuple[PlatformAdapter, ...]:
        with self._lock:
            return tuple(self._adapters[key] for key in sorted(self._adapters))


__all__ = ["DestinationEntry", "DestinationError", "DestinationRegistry"]
