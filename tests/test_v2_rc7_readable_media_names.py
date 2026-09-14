from __future__ import annotations

from types import SimpleNamespace

from content_agent.google_drive import DriveMediaInfo
from content_agent.managed_media_drive import ManagedGoogleDriveClient
from content_agent.media_candidates import ValidatedMedia
from content_agent.readable_media_names import install_runtime, readable_post_media_filename
from content_agent.v2.ui.window_rc7 import _ReadableMediaDriveClient
from content_agent.worker import PublicationWorker


def _info(name: str = "opaque_hash_123.jpg") -> DriveMediaInfo:
    return DriveMediaInfo(
        file_id="file123",
        name=name,
        mime_type="image/jpeg",
        size=4,
        kind="image",
        can_download=True,
        can_delete=True,
        can_share=True,
        public_url="",
        public_direct=False,
    )


def test_readable_filename_uses_post_title_and_short_id() -> None:
    name = readable_post_media_filename(
        "Трамп заявив, що єменські хусити пообіцяли йому не перекривати Баб-ель-Мандебський пролив",
        1842,
        "image/jpeg",
    )
    assert name.endswith("- post-1842.jpg")
    assert name.startswith("Трамп заявив")
    assert len(name) <= 160
    assert "opaque" not in name


def test_readable_filename_sanitizes_markup_and_keeps_extension() -> None:
    name = readable_post_media_filename("Новина: <тест> / 2026?", 77, "video/mp4")
    assert name == "Новина тест 2026 - post-77.mp4"


def test_managed_upload_ignores_source_hash_filename(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_upload(self, media, filename, *, folder_id="", folder_name="UA FREE Content Tool Media"):
        captured["filename"] = filename
        return SimpleNamespace(info=_info(filename), folder_id="folder")

    monkeypatch.setattr(ManagedGoogleDriveClient, "upload_validated_media", fake_upload)
    client = _ReadableMediaDriveClient(
        "client",
        "secret",
        "refresh",
        post_title="Людська назва посту",
        group_id=55,
    )
    media = ValidatedMedia(b"\xff\xd8\xffx", "image", "image/jpeg", "https://cdn/x9Q_hash.jpg", 4)
    client.upload_validated_media(media, "x9Q_hash.jpg")

    assert captured["filename"] == "Людська назва посту - post-55.jpg"


def test_publication_runtime_replaces_legacy_drive_hash_name(monkeypatch) -> None:
    install_runtime()

    group = SimpleNamespace(
        media_file_id="file123",
        headline="Зрозумілий заголовок",
        canonical_title="Резервний заголовок",
    )

    class FakeDatabase:
        @staticmethod
        def group_id_for_article(_article_id: int) -> int:
            return 91

        @staticmethod
        def get_group(_group_id: int):
            return group

    class FakeDrive:
        @staticmethod
        def inspect_media(_file_id: str, probe_public: bool = False):
            assert probe_public is False
            return _info("s43_PhHPvw3rn_E5biqDJw4h0Qbkla.jpg")

        @staticmethod
        def download_media(_info: DriveMediaInfo) -> bytes:
            return b"\xff\xd8\xffx"

    fake_worker = SimpleNamespace(database=FakeDatabase(), _drive_client=lambda: FakeDrive())
    media, _client, group_id, _drive_info = PublicationWorker._load_media(fake_worker, 123)

    assert group_id == 91
    assert media is not None
    assert media.name == "Зрозумілий заголовок - post-91.jpg"
