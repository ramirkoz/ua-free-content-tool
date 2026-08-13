from pathlib import Path

import pytest

from content_agent.config import AppConfig
from content_agent.media_gallery_v1_2_rc4 import ImageGalleryPayload
from content_agent.models import MediaPayload
from content_agent.multi_image_store_v1_2_rc4 import MultiImageStore, MultiImageStoreError, StoredImageAttachment
from content_agent.worker_v1_2_rc4 import Rc4PublicationWorker


def _image(file_id: str) -> StoredImageAttachment:
    return StoredImageAttachment(file_id, f"{file_id}.jpg", "image/jpeg", 100, f"https://drive/{file_id}")


def _payload(file_id: str) -> MediaPayload:
    return MediaPayload(file_id, f"{file_id}.jpg", "image", "image/jpeg", b"image", f"https://public/{file_id}")


def test_instagram_is_opt_in() -> None:
    config = AppConfig(instagram_user_id="123", instagram_token="token")
    assert not config.platform_ready("instagram")
    config.instagram_enabled = True
    assert config.platform_ready("instagram")


def test_multi_image_store_preserves_order(tmp_path: Path) -> None:
    store = MultiImageStore(tmp_path / "gallery.json")
    store.set_group(7, [_image("a"), _image("b")])
    assert [item.file_id for item in store.list_group(7)] == ["a", "b"]


def test_multi_image_store_rejects_video(tmp_path: Path) -> None:
    store = MultiImageStore(tmp_path / "gallery.json")
    with pytest.raises(MultiImageStoreError):
        store.set_group(7, [StoredImageAttachment("v", "v.mp4", "video/mp4", 100, "https://drive/v")])


def test_gallery_payload_is_image_only() -> None:
    gallery = ImageGalleryPayload([_payload("a"), _payload("b")])
    assert gallery.kind == "image"
    with pytest.raises(ValueError):
        ImageGalleryPayload([_payload("a")])


def test_catchup_gap_is_five_minutes() -> None:
    assert Rc4PublicationWorker.CATCHUP_GAP_SECONDS == 300
