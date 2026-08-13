from __future__ import annotations

from dataclasses import dataclass

from .models import MediaPayload
from .multi_image_store_v1_2_rc4 import MAX_IMAGE_ATTACHMENTS


@dataclass(slots=True)
class ImageGalleryPayload:
    items: list[MediaPayload]

    def __post_init__(self) -> None:
        if not (2 <= len(self.items) <= MAX_IMAGE_ATTACHMENTS):
            raise ValueError(f"Галерея повинна містити від 2 до {MAX_IMAGE_ATTACHMENTS} фото.")
        if any(item.kind != "image" or not item.mime_type.casefold().startswith("image/") for item in self.items):
            raise ValueError("У галереї дозволені тільки зображення.")

    @property
    def first(self) -> MediaPayload:
        return self.items[0]

    @property
    def file_id(self) -> str:
        return self.first.file_id

    @property
    def name(self) -> str:
        return self.first.name

    @property
    def kind(self) -> str:
        return "image"

    @property
    def mime_type(self) -> str:
        return self.first.mime_type

    @property
    def data(self) -> bytes:
        return self.first.data

    @property
    def public_url(self) -> str:
        return self.first.public_url
