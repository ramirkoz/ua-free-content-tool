from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from ..google_drive import GoogleDriveError
from ..media_candidates import ValidatedMedia
from ..readable_media_names import readable_post_media_filename
from ..strict_media_drive import StrictManagedGoogleDriveClient, validate_decodable_image

_INSTAGRAM_MIN_RATIO = 4 / 5
_INSTAGRAM_MAX_RATIO = 1.91
_INSTAGRAM_MIN_WIDTH = 320
_INSTAGRAM_MAX_WIDTH = 1440


def normalize_instagram_safe_image(media: ValidatedMedia) -> ValidatedMedia:
    """Preserve the picture but normalize static images to Instagram feed constraints."""
    if media.kind != "image" or media.mime_type == "image/gif":
        return media
    validate_decodable_image(media)
    try:
        with Image.open(BytesIO(media.data)) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()
            if image.mode not in {"RGB", "L"}:
                background = Image.new("RGB", image.size, "white")
                if "A" in image.getbands():
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image.convert("RGB"))
                image = background
            elif image.mode == "L":
                image = image.convert("RGB")

            width, height = image.size
            if width < _INSTAGRAM_MIN_WIDTH:
                scale = _INSTAGRAM_MIN_WIDTH / float(width)
                image = image.resize((round(width * scale), round(height * scale)), Image.Resampling.LANCZOS)
            elif width > _INSTAGRAM_MAX_WIDTH:
                scale = _INSTAGRAM_MAX_WIDTH / float(width)
                image = image.resize((round(width * scale), round(height * scale)), Image.Resampling.LANCZOS)

            width, height = image.size
            ratio = width / float(height)
            if ratio < _INSTAGRAM_MIN_RATIO:
                target_width = round(height * _INSTAGRAM_MIN_RATIO)
                canvas = Image.new("RGB", (target_width, height), "white")
                canvas.paste(image, ((target_width - width) // 2, 0))
                image = canvas
            elif ratio > _INSTAGRAM_MAX_RATIO:
                target_height = round(width / _INSTAGRAM_MAX_RATIO)
                canvas = Image.new("RGB", (width, target_height), "white")
                canvas.paste(image, (0, (target_height - height) // 2))
                image = canvas

            output = BytesIO()
            image.save(output, format="JPEG", quality=92, optimize=True)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise GoogleDriveError("Не вдалося підготувати зображення до Instagram-сумісного формату.") from exc
    data = output.getvalue()
    return ValidatedMedia(data=data, kind="image", mime_type="image/jpeg", source_url=media.source_url, size=len(data))


class Rc56ManagedGoogleDriveClient(StrictManagedGoogleDriveClient):
    """RC56 validation plus the readable media-name contract restored in RC59."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        *,
        post_title: str = "",
        group_id: int = 0,
    ) -> None:
        super().__init__(client_id, client_secret, refresh_token)
        self._post_title = str(post_title or "")
        self._group_id = int(group_id or 0)

    def _publication_filename(self, mime_type: str) -> str:
        return readable_post_media_filename(self._post_title, self._group_id, mime_type)

    def upload_validated_media(self, media: ValidatedMedia, filename: str, *, folder_id: str = "", folder_name: str = "UA FREE Content Tool Media"):
        del filename
        return super().upload_validated_media(
            normalize_instagram_safe_image(media),
            self._publication_filename(media.mime_type),
            folder_id=folder_id,
            folder_name=folder_name,
        )
