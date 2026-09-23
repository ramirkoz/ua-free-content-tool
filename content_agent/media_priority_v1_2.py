from __future__ import annotations

from collections.abc import Iterable

from .media_candidates import MediaCandidate


def prioritize_media_candidates(candidates: Iterable[MediaCandidate]) -> list[MediaCandidate]:
    """Put real video ahead of posters/thumbnails from the same source.

    Telegram and news pages often expose a high-scored og:image/poster next to a
    lower-scored video URL. Sorting only by the raw discovery score made the
    screenshot appear first even when the article actually contained video.
    """

    items = list(candidates)
    sources_with_video = {
        (item.source_label or "").strip().casefold()
        for item in items
        if item.kind == "video"
    }

    def key(item: MediaCandidate) -> tuple[int, int, int, str]:
        source_key = (item.source_label or "").strip().casefold()
        is_video = item.kind == "video"
        image_is_fallback_for_video = (
            not is_video
            and source_key in sources_with_video
            and (
                "poster" in item.origin.casefold()
                or "thumbnail" in item.origin.casefold()
                or item.origin.casefold() in {"og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src", "html:background-image"}
            )
        )
        priority = 0 if is_video else (2 if image_is_fallback_for_video else 1)
        area = int(item.width or 0) * int(item.height or 0)
        return (priority, -int(item.score or 0), -area, item.url.casefold())

    return sorted(items, key=key)


def prefer_real_video(candidates: Iterable[MediaCandidate]) -> list[MediaCandidate]:
    """RC3 compatibility name for the same video-first ordering."""

    return prioritize_media_candidates(candidates)
