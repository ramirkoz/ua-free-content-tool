from __future__ import annotations

from io import BytesIO

from PIL import Image
import pytest

from content_agent.google_drive import GoogleDriveError
from content_agent.ui.media_preview import make_thumbnail


def _png_bytes(size: tuple[int, int]) -> bytes:
    image = Image.new("RGB", size, (20, 30, 40))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_thumbnail_is_detached_and_bounded() -> None:
    thumbnail = make_thumbnail(_png_bytes((1200, 800)), (280, 190))
    assert thumbnail.mode == "RGBA"
    assert thumbnail.width <= 280
    assert thumbnail.height <= 190
    assert thumbnail.getpixel((0, 0))[:3] == (20, 30, 40)


def test_thumbnail_rejects_invalid_image_bytes() -> None:
    with pytest.raises(GoogleDriveError, match="безпечно відкрити"):
        make_thumbnail(b"not-an-image")
