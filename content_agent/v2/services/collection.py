from __future__ import annotations

from ...collectors import collect_source


class CollectionService:
    """Stable collection boundary used by V2 composition."""

    def collect(self, source):
        return collect_source(source)
