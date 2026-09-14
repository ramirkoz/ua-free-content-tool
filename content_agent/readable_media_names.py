from __future__ import annotations

import re
from typing import Any

from .managed_media_drive import safe_media_filename

_TITLE_SAFE_RE = re.compile(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ -]+")
_SPACES_RE = re.compile(r"\s+")
_RUNTIME_INSTALLED = False


def readable_post_media_filename(
    title: str,
    group_id: int,
    mime_type: str,
    *,
    max_title_chars: int = 96,
) -> str:
    """Build a short, human-readable platform filename from the publication title."""
    cleaned = _TITLE_SAFE_RE.sub(" ", str(title or ""))
    cleaned = _SPACES_RE.sub(" ", cleaned).strip(" -")
    if not cleaned:
        cleaned = "Медіа публікації"
    cleaned = cleaned[: max(24, int(max_title_chars))].rstrip(" -")
    try:
        numeric_group_id = int(group_id)
    except (TypeError, ValueError):
        numeric_group_id = 0
    suffix = f" - post-{numeric_group_id}" if numeric_group_id > 0 else ""
    return safe_media_filename(f"{cleaned}{suffix}", mime_type)


def _group_title(group: Any) -> str:
    return str(getattr(group, "headline", "") or getattr(group, "canonical_title", "") or "").strip()


def install_runtime() -> None:
    """Force readable multipart filenames even for media attached before RC7."""
    global _RUNTIME_INSTALLED
    if _RUNTIME_INSTALLED:
        return

    from .worker import PublicationWorker

    original = PublicationWorker._load_media
    if getattr(original, "_ua_free_readable_media_names", False):
        _RUNTIME_INSTALLED = True
        return

    def load_media_with_readable_name(self: Any, batch_article_id: int):
        media, client, group_id, info = original(self, batch_article_id)
        if media is not None:
            try:
                group = self.database.get_group(group_id)
                media.name = readable_post_media_filename(
                    _group_title(group),
                    group_id,
                    media.mime_type,
                )
            except Exception:
                # Filename cosmetics must never block an otherwise valid publication.
                pass
        return media, client, group_id, info

    load_media_with_readable_name._ua_free_readable_media_names = True  # type: ignore[attr-defined]
    PublicationWorker._load_media = load_media_with_readable_name  # type: ignore[method-assign]
    _RUNTIME_INSTALLED = True
