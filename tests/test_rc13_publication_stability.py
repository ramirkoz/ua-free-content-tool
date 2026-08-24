from __future__ import annotations

import time

import pytest

from content_agent.google_drive import DriveMediaInfo, GoogleDriveClient, GoogleDriveError
from content_agent.network import HttpResponse
from content_agent.worker import PublicationWorker, WorkerResult


class _LeaseDb:
    def assert_lease(self, _batch_id: int, _owner: str) -> None:
        return

    def renew_lease(self, _batch_id: int, _owner: str, _seconds: int) -> None:
        return


def test_generic_publication_drive_inspection_skips_threads_public_probe(monkeypatch) -> None:
    metadata = (
        b'{"id":"1AbCdEfGhIjKlMnOpQrStUvWxYz_12345","name":"photo.jpg",'
        b'"mimeType":"image/jpeg","size":"123","trashed":false,'
        b'"capabilities":{"canDownload":true,"canDelete":true,"canShare":true}}'
    )
    monkeypatch.setattr(
        "content_agent.google_drive.fetch_url",
        lambda url, **_kwargs: HttpResponse(200, {"content-type": "application/json"}, metadata, url),
    )
    monkeypatch.setattr(
        "content_agent.google_drive.probe_public_media",
        lambda _file_id: (_ for _ in ()).throw(AssertionError("unexpected Threads public probe")),
    )
    client = GoogleDriveClient("client.apps.googleusercontent.com", "secret", "refresh")
    client._access_token = "access"
    info = client.inspect_media("1AbCdEfGhIjKlMnOpQrStUvWxYz_12345", probe_public=False)
    assert info.public_direct is False
    assert info.mime_type == "image/jpeg"


def test_threads_reuses_existing_public_access_without_creating_permission(monkeypatch) -> None:
    monkeypatch.setattr("content_agent.google_drive.probe_public_media", lambda _file_id: (True, "image/jpeg"))
    monkeypatch.setattr(
        "content_agent.google_drive.fetch_url",
        lambda _url, **_kwargs: (_ for _ in ()).throw(AssertionError("permission POST must not run")),
    )
    client = GoogleDriveClient("client.apps.googleusercontent.com", "secret", "refresh")
    client._access_token = "access"
    info = DriveMediaInfo(
        file_id="1AbCdEfGhIjKlMnOpQrStUvWxYz_12345", name="photo.jpg", mime_type="image/jpeg",
        size=123, kind="image", can_download=True, can_delete=True, can_share=True,
        public_url="https://drive.google.com/uc?export=download&id=x", public_direct=False,
    )
    assert client.ensure_public_for_threads(info) == ""


def test_drive_preflight_reuses_late_inflight_job(monkeypatch) -> None:
    worker = PublicationWorker(_LeaseDb(), object(), media_preflight_timeout_seconds=1.0)  # type: ignore[arg-type]
    worker.media_preflight_timeout_seconds = 0.05
    calls: list[int] = []
    expected = (None, None, 77, None)

    def slow_load(_article_id: int):
        calls.append(1)
        time.sleep(0.28)
        return expected

    monkeypatch.setattr(worker, "_load_media", slow_load)
    with pytest.raises(GoogleDriveError, match="не дублюється"):
        worker._load_media_cancellable(batch_id=273, batch_article_id=1, owner="owner")
    assert worker._load_media_cancellable(batch_id=273, batch_article_id=1, owner="owner") == expected
    assert len(calls) == 1


def test_worker_result_distinguishes_explicit_cancellation() -> None:
    value = WorkerResult(claimed=True, batch_id=273, cancelled=True)
    assert value.cancelled is True
    assert value.failed_platforms == {}
