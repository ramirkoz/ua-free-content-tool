from __future__ import annotations

from .media_candidates import MediaCandidate
from .models import Article


def order_media_by_source(
    candidates: list[MediaCandidate],
    articles: list[Article],
) -> list[MediaCandidate]:
    order: dict[str, int] = {}
    for index, article in enumerate(articles):
        label = str(article.source_name or article.title or article.url or "").strip().casefold()
        if label and label not in order:
            order[label] = index
    video_sources = {
        str(item.source_label or "").strip().casefold()
        for item in candidates
        if item.kind == "video"
    }

    def key(item: MediaCandidate) -> tuple[int, int, int, str]:
        source = str(item.source_label or "").strip().casefold()
        origin = item.origin.casefold()
        fallback = (
            item.kind != "video"
            and source in video_sources
            and ("poster" in origin or "thumbnail" in origin)
        )
        kind_rank = 0 if item.kind == "video" else (2 if fallback else 1)
        return (
            kind_rank,
            order.get(source, len(order) + 10),
            -int(item.score or 0),
            item.url.casefold(),
        )

    return sorted(candidates, key=key)
