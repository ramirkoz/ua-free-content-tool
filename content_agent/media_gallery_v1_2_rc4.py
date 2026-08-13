from __future__ import annotations

from dataclasses import dataclass

from .models import MediaPayload


@dataclass(slots=True)
class ImageGalleryPayload:
    items: list[MediaPayload]
