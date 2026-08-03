from __future__ import annotations

import pytest

from content_agent.google_drive import GoogleDriveClient, GoogleDriveError, extract_drive_file_id, public_download_url
from content_agent.network import HttpResponse


def test_extracts_google_drive_file_id_from_supported_links() -> None:
    file_id = "1AbCdEfGhIjKlMnOpQrStUvWxYz_12345"
    assert extract_drive_file_id(f"https://drive.google.com/file/d/{file_id}/view?usp=sharing") == file_id
    assert extract_drive_file_id(f"https://drive.google.com/open?id={file_id}") == file_id
    assert extract_drive_file_id(public_download_url(file_id)) == file_id


def test_rejects_non_drive_media_link() -> None:
    with pytest.raises(GoogleDriveError):
        extract_drive_file_id("https://t.me/c/1117030092/125430")


def test_delete_file_uses_permanent_drive_delete(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return HttpResponse(204, {}, b"", url)

    client = GoogleDriveClient("client.apps.googleusercontent.com", "secret", "refresh")
    client._access_token = "access"
    monkeypatch.setattr("content_agent.google_drive.fetch_url", fake_fetch)
    client.delete_file("1AbCdEfGhIjKlMnOpQrStUvWxYz_12345")
    assert captured["method"] == "DELETE"
    assert "supportsAllDrives=true" in str(captured["url"])
    assert "body" not in captured or captured["body"] is None


def test_delete_file_fails_closed_on_drive_error(monkeypatch) -> None:
    client = GoogleDriveClient("client.apps.googleusercontent.com", "secret", "refresh")
    client._access_token = "access"
    monkeypatch.setattr(
        "content_agent.google_drive.fetch_url",
        lambda *args, **kwargs: HttpResponse(403, {"content-type": "application/json"}, b"{}", str(args[0])),
    )
    with pytest.raises(GoogleDriveError):
        client.delete_file("1AbCdEfGhIjKlMnOpQrStUvWxYz_12345")
