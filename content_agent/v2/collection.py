from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..collectors import collect_source
from ..models import CollectedArticle, Source


Collector = Callable[[Source], list[CollectedArticle]]


@dataclass(frozen=True, slots=True)
class SourceAdapter:
    kind: str
    collect: Collector


class CollectionService:
    """Explicit source-collection boundary used by composition and future UI code."""

    def __init__(self, adapters: tuple[SourceAdapter, ...] | None = None) -> None:
        configured = adapters or tuple(
            SourceAdapter(kind, collect_source) for kind in ("rss", "telegram", "url")
        )
        self._adapters = {adapter.kind: adapter for adapter in configured}

    def adapter_for(self, source: Source) -> SourceAdapter:
        kind = str(source.kind or "").strip().casefold()
        adapter = self._adapters.get(kind)
        if adapter is None:
            raise ValueError(f"Unsupported source kind: {source.kind}")
        return adapter

    def collect(self, source: Source) -> list[CollectedArticle]:
        return self.adapter_for(source).collect(source)

    def supported_kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


__all__ = ["CollectionService", "SourceAdapter"]
