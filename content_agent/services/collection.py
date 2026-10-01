from __future__ import annotations

from typing import Protocol

from ..collectors import collect_source
from ..models import CollectedArticle, Source


class SourceAdapter(Protocol):
    """Source collection boundary used by the active composition root."""

    def collect(self, source: Source) -> list[CollectedArticle]: ...


class BuiltinSourceAdapter:
    """Adapter over the proven RSS/Telegram/URL collectors."""

    def collect(self, source: Source) -> list[CollectedArticle]:
        return collect_source(source)


class CollectionService:
    def __init__(self, adapter: SourceAdapter | None = None) -> None:
        self.adapter = adapter or BuiltinSourceAdapter()

    def collect(self, source: Source) -> list[CollectedArticle]:
        return self.adapter.collect(source)


__all__ = ["SourceAdapter", "BuiltinSourceAdapter", "CollectionService"]
