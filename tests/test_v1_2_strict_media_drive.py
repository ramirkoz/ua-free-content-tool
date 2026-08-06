from __future__ import annotations

from io import BytesIO

from PIL import Image
import pytest

from content_agent.google_drive import GoogleDriveError
from content_agent.media_candidates import ValidatedMedia
from content_agent.strict_media_drive import validate_decodable_image


def _image_bytes(size: tuple[int, int], image_format: str = "PNG") -> bytes:
    image = Image.new("RGB", size, (40, 80, 120))
    output = BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def _media(data: bytes, *, kind: str = "image", mime_type: str = "image/png") -> ValidatedMedia:
    return ValidatedMedia(
        data=data,
        kind=kind,
        mime_type=mime_type,
        source_url="https://example.test/media",
        size=len(data),
    )


def test_valid_publication_image_is_fully_decoded() -> None:
    assert validate_decodable_image(_media(_image_bytes((1200, 800)))) == (1200, 800)


def test_small_image_is_rejected_before_drive_upload() -> None:
    with pytest.raises(GoogleDriveError, match="надто мале"):
        validate_decodable_image(_media(_image_bytes((179, 900))))


def test_corrupt_image_with_valid_signature_is_rejected() -> None:
    with pytest.raises(GoogleDriveError, match="пошкоджене"):
        validate_decodable_image(_media(b"\x89PNG\r\n\x1a\nnot-a-real-png"))


def test_video_skips_image_decoder() -> None:
    media = _media(b"video-data", kind="video", mime_type="video/mp4")
    assert validate_decodable_image(media) == (0, 0)
