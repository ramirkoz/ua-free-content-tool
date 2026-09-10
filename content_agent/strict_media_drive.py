from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from .google_drive import GoogleDriveError
from .managed_media_drive import ManagedGoogleDriveClient, ManagedMediaUpload
from .media_candidates import ValidatedMedia

_MIN_IMAGE_SIDE = 180
_MIN_UPSCALE_SOURCE_SIDE = 96
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
    if min(width, height) < _MIN_UPSCALE_SOURCE_SIDE:
        raise GoogleDriveError(
            f"Зображення справді надто мале для публікації: {width}×{height}. "
            f"Мінімальна вихідна сторона для безпечного масштабування — {_MIN_UPSCALE_SOURCE_SIDE}px."
        )
    return width, height


def normalize_decodable_image(media: ValidatedMedia) -> ValidatedMedia:
    """Decode and minimally upscale small, but still usable, static images.

    Telegram embeds frequently expose 320×175 preview photos. Rejecting such a
    preview because it misses the historical 180px threshold by five pixels is
    pointless. We preserve aspect ratio and only enlarge enough to meet the
    publication floor. Tiny icon-sized inputs are still rejected.
    """

    width, height = validate_decodable_image(media)
    if media.kind != "image" or min(width, height) >= _MIN_IMAGE_SIDE:
        return media
    if media.mime_type == "image/gif":
        raise GoogleDriveError(
            f"GIF {width}×{height} замалий для публікації; автоматичне масштабування анімованого GIF вимкнено."
        )
    scale = _MIN_IMAGE_SIDE / float(min(width, height))
    target = (max(_MIN_IMAGE_SIDE, round(width * scale)), max(_MIN_IMAGE_SIDE, round(height * scale)))
    try:
        with Image.open(BytesIO(media.data)) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()
            resized = image.resize(target, Image.Resampling.LANCZOS)
            output = BytesIO()
            mime = media.mime_type
            if mime == "image/png":
                resized.save(output, format="PNG", optimize=True)
            elif mime == "image/webp":
                resized.save(output, format="WEBP", quality=92, method=4)
            else:
                if resized.mode not in {"RGB", "L"}:
                    background = Image.new("RGB", resized.size, "white")
                    if "A" in resized.getbands():
                        background.paste(resized, mask=resized.getchannel("A"))
                    else:
                        background.paste(resized.convert("RGB"))
                    resized = background
                elif resized.mode == "L":
                    resized = resized.convert("RGB")
                resized.save(output, format="JPEG", quality=92, optimize=True)
                mime = "image/jpeg"
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise GoogleDriveError("Не вдалося підготувати мале зображення до публікації.") from exc
    data = output.getvalue()
    return ValidatedMedia(
        data=data,
        kind="image",
        mime_type=mime,
        source_url=media.source_url,
        size=len(data),
    )


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
        normalized = normalize_decodable_image(media)
        return super().upload_validated_media(
            normalized,
            filename,
            folder_id=folder_id,
            folder_name=folder_name,
        )
