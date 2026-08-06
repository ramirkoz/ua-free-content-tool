from __future__ import annotations

from pathlib import Path

import pytest

from content_agent.google_drive import DriveMediaInfo, GoogleDriveError
from content_agent.managed_media_drive import (
    ManagedGoogleDriveClient,
    safe_media_filename,
    validate_local_media,
)
from content_agent.media_candidates import ValidatedMedia


def _drive_info(file_id: str, mime_type: str = "image/jpeg", size: int = 4) -> DriveMediaInfo:
    return DriveMediaInfo(
        file_id=file_id,
        name="photo.jpg",
        mime_type=mime_type,
        size=size,
        kind="image" if mime_type.startswith("image/") else "video",
        can_download=True,
        can_delete=True,
        can_share=True,
        public_url="",
        public_direct=False,
    )


def test_filename_is_sanitized_and_extension_matches() -> None:
    assert safe_media_filename("../небезпечне<>.exe", "image/jpeg") == "небезпечне.jpg"
    assert safe_media_filename("photo.png", "image/png") == "photo.png"


def test_validate_local_media_uses_file_signature(tmp_path: Path) -> None:
    path = tmp_path / "photo.any"
    path.write_bytes(b"\xff\xd8\xffx")
    media, name = validate_local_media(path)
    assert media.mime_type == "image/jpeg"
    assert name == "photo.jpg"


def test_ensure_folder_uses_existing_managed_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ManagedGoogleDriveClient("client", "secret", "refresh")
    calls: list[tuple[str, dict[str, object]]] = []

    def request(url: str, **kwargs: object) -> dict[str, object]:
        calls.append((url, kwargs))
        return {"files": [{"id": "folder123", "name": "UA FREE Content Tool Media"}]}

    monkeypatch.setattr(client, "_request_json", request)
    assert client.ensure_media_folder() == "folder123"
    assert "appProperties" in calls[0][0]


def test_upload_builds_multipart_and_verifies_file(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ManagedGoogleDriveClient("client", "secret", "refresh")
    monkeypatch.setattr(client, "ensure_media_folder", lambda *args, **kwargs: "folder123")
    captured: dict[str, object] = {}

    def request(url: str, **kwargs: object) -> dict[str, object]:
        captured["url"] = url
        captured.update(kwargs)
        return {"id": "file123", "name": "photo.jpg", "mimeType": "image/jpeg", "size": "4"}

    monkeypatch.setattr(client, "_request_json", request)
    monkeypatch.setattr(client, "inspect_media", lambda file_id: _drive_info(file_id))
    media = ValidatedMedia(b"\xff\xd8\xffx", "image", "image/jpeg", "https://x/a", 4)

    result = client.upload_validated_media(media, "photo.bad")

    assert result.folder_id == "folder123"
    assert result.info.file_id == "file123"
    body = captured["body"]
    headers = captured["headers"]
    assert isinstance(body, bytes)
    assert isinstance(headers, dict)
    assert b'"uaFreeManaged": "1"' in body
    assert b"Content-Type: image/jpeg" in body
    assert str(headers["Content-Type"]).startswith("multipart/related")


def test_upload_deletes_file_when_drive_verification_differs(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ManagedGoogleDriveClient("client", "secret", "refresh")
    monkeypatch.setattr(client, "ensure_media_folder", lambda *args, **kwargs: "folder123")
    monkeypatch.setattr(client, "_request_json", lambda *args, **kwargs: {"id": "file123"})
    monkeypatch.setattr(client, "inspect_media", lambda file_id: _drive_info(file_id, "image/png", 8))
    deleted: list[str] = []
    monkeypatch.setattr(client, "delete_file", deleted.append)
    media = ValidatedMedia(b"\xff\xd8\xffx", "image", "image/jpeg", "https://x/a", 4)

    with pytest.raises(GoogleDriveError, match="іншим типом"):
        client.upload_validated_media(media, "photo.jpg")

    assert deleted == ["file123"]
