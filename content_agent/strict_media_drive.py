from __future__ import annotations

from io import BytesIO

from PIL import Image, UnidentifiedImageError

from .google_drive import GoogleDriveError
from .managed_media_drive import ManagedGoogleDriveClient, ManagedMediaUpload
from .media_candidates import ValidatedMedia

_MIN_IMAGE_SIDE = 180
_MAX_IMAGE_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS


def validate_decodable_image(media: ValidatedMedia) -> tuple[int, int]:
    """Verify actual image bytes before uploading them to Google Drive."""

    if media.kind != "image":
        return 0, 0
    try:
        with Image.open(BytesIO(media.data)) as image:
            image.verify()
        with Image.open(BytesIO(media.data)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise GoogleDriveError("Зображення пошкоджене або має небезпечний формат.") from exc
    if width <= 0 or height <= 0:
        raise GoogleDriveError("Не вдалося визначити розмір зображення.")
    if width * height > _MAX_IMAGE_PIXELS:
        raise GoogleDriveError("Зображення має надто велику кількість пікселів.")
    if min(width, height) < _MIN_IMAGE_SIDE:
        raise GoogleDriveError(
            f"Зображення надто мале для публікації: {width}×{height}. Мінімальна сторона — {_MIN_IMAGE_SIDE}px."
        )
    return width, height


class StrictManagedGoogleDriveClient(ManagedGoogleDriveClient):
    """Managed Drive client with real image decoding before upload."""

    def upload_validated_media(
        self,
        media: ValidatedMedia,
        filename: str,
        *,
        folder_id: str = "",
        folder_name: str = "UA FREE Content Tool Media",
    ) -> ManagedMediaUpload:
        validate_decodable_image(media)
        return super().upload_validated_media(
            media,
            filename,
            folder_id=folder_id,
            folder_name=folder_name,
        )
