from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from content_agent.config import AppConfig
from content_agent.database import Database
from content_agent.google_drive import DriveMediaInfo, GoogleDriveClient
from content_agent.models import CollectedArticle, MediaPayload
from content_agent.network import HttpResponse
from content_agent.publishers import PublishContext, PublishError, PublishResult, Publisher, PublisherFactory
from content_agent.scheduling import KYIV
from content_agent.ui import main_window
from content_agent.ui.main_window import MainWindow
from content_agent.worker import PublicationWorker


class DummyVar:
    def __init__(self, value: str = ""):
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class NoWriteDatabase:
    def set_group_media(self, *_args, **_kwargs) -> None:
        raise AssertionError("verification without an open group must not write")


def test_private_drive_file_verifies_without_manual_public_sharing(monkeypatch) -> None:
    window = MainWindow.__new__(MainWindow)
    window.current_group_id = None
    window.media_url_var = DummyVar(
        "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz_12345/view"
    )
    window.media_status_var = DummyVar("Медіа не додано")
    window.config = AppConfig(
        google_client_id="client.apps.googleusercontent.com",
        google_client_secret="secret",
        google_refresh_token="refresh",
    )
    window.db = NoWriteDatabase()

    class FakeClient:
        def __init__(self, *_args: str):
            pass

        def inspect_media(self, file_id: str) -> object:
            return SimpleNamespace(
                public_direct=False,
                can_delete=True,
                can_share=True,
                file_id=file_id,
                name="private-photo.jpg",
                kind="image",
                mime_type="image/jpeg",
                size=1024,
            )

    monkeypatch.setattr(main_window, "GoogleDriveClient", FakeClient)

    def run_async(action, success=None, **_kwargs):
        result = action()
        if success:
            success(result)

    window.run_async = run_async  # type: ignore[method-assign]
    window.verify_media()
    status = window.media_status_var.get()
    assert status.startswith("✓ Перевірено: IMAGE · private-photo.jpg")
    assert "сама тимчасово відкриє доступ" in status
    assert "Усі, хто має посилання" not in status


def test_drive_creates_and_revokes_temporary_threads_permission(monkeypatch) -> None:
    calls: list[tuple[str, str, bytes | None]] = []

    def fake_fetch(url: str, **kwargs):
        method = str(kwargs.get("method", "GET"))
        body = kwargs.get("body")
        calls.append((method, url, body if isinstance(body, bytes) else None))
        if method == "POST":
            return HttpResponse(200, {"content-type": "application/json"}, b'{"id":"perm-123"}', url)
        return HttpResponse(204, {}, b"", url)

    monkeypatch.setattr("content_agent.google_drive.fetch_url", fake_fetch)
    probes = iter([(False, ""), (True, "image/jpeg")])
    monkeypatch.setattr("content_agent.google_drive.probe_public_media", lambda _file_id: next(probes))
    client = GoogleDriveClient("client.apps.googleusercontent.com", "secret", "refresh")
    client._access_token = "access"
    info = DriveMediaInfo(
        file_id="1AbCdEfGhIjKlMnOpQrStUvWxYz_12345",
        name="photo.jpg",
        mime_type="image/jpeg",
        size=123,
        kind="image",
        can_download=True,
        can_delete=True,
        can_share=True,
        public_url="https://drive.google.com/uc?export=download&id=x",
        public_direct=False,
    )
    permission_id = client.ensure_public_for_threads(info)
    assert permission_id == "perm-123"
    assert calls[0][0] == "POST"
    assert b'"type":"anyone"' in (calls[0][2] or b"")
    assert b'"role":"reader"' in (calls[0][2] or b"")
    client.remove_permission(info.file_id, permission_id)
    assert calls[-1][0] == "DELETE"
    assert "/permissions/perm-123" in calls[-1][1]


def test_public_probe_falls_back_from_head_to_ranged_get(monkeypatch) -> None:
    calls: list[str] = []

    def fake_fetch(url: str, **kwargs):
        method = str(kwargs.get("method", "GET"))
        calls.append(method)
        if method == "HEAD":
            return HttpResponse(200, {"content-type": "text/html"}, b"", url)
        return HttpResponse(206, {"content-type": "image/jpeg"}, b"x", url)

    monkeypatch.setattr("content_agent.google_drive.fetch_url", fake_fetch)
    from content_agent.google_drive import probe_public_media

    assert probe_public_media("1AbCdEfGhIjKlMnOpQrStUvWxYz_12345") == (True, "image/jpeg")
    assert calls == ["HEAD", "GET"]


class ThreadsPublisher(Publisher):
    def __init__(self, fail: bool):
        self.fail = fail

    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media=None) -> PublishResult:
        context.before_write()
        assert media is not None and media.public_url
        if self.fail:
            raise PublishError("threads failed")
        return PublishResult(remote_id="threads-ok", progress={})


class ThreadsFactory(PublisherFactory):
    def __init__(self, publisher: ThreadsPublisher):
        super().__init__(AppConfig())
        self.publisher = publisher

    def create(self, platform: str) -> Publisher:
        assert platform == "threads"
        return self.publisher


class TemporaryDrive:
    def __init__(self):
        self.created: list[str] = []
        self.revoked: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def ensure_public_for_threads(self, info: DriveMediaInfo) -> str:
        self.created.append(info.file_id)
        return "temp-permission"

    def remove_permission(self, file_id: str, permission_id: str) -> None:
        self.revoked.append((file_id, permission_id))

    def delete_file(self, file_id: str) -> None:
        self.deleted.append(file_id)


def _threads_batch(tmp_path: Path) -> tuple[Database, int, int, DriveMediaInfo, MediaPayload]:
    db = Database(tmp_path / "db.sqlite3")
    source = db.add_source("rss", "Source", "https://example.com/feed")
    db.insert_collected(source, [CollectedArticle(
        "a", "Новина", "https://example.com/a", "Повний текст", datetime.now(KYIV).isoformat()
    )])
    group = db.get_group(db.list_groups()[0].id)
    file_id = "1AbCdEfGhIjKlMnOpQrStUvWxYz_12345"
    db.set_group_media(
        group.id,
        drive_url=f"https://drive.google.com/file/d/{file_id}/view",
        file_id=file_id,
        name="photo.jpg",
        kind="image",
        mime="image/jpeg",
        size=5,
    )
    batch = db.create_batch(
        db.lead_article_id(group.id),
        (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        {"threads": "text"},
    )
    info = DriveMediaInfo(
        file_id=file_id,
        name="photo.jpg",
        mime_type="image/jpeg",
        size=5,
        kind="image",
        can_download=True,
        can_delete=True,
        can_share=True,
        public_url="https://drive.google.com/uc?export=download&id=x",
        public_direct=False,
    )
    media = MediaPayload(
        file_id=file_id,
        name="photo.jpg",
        kind="image",
        mime_type="image/jpeg",
        data=b"image",
        public_url=info.public_url,
    )
    return db, group.id, batch, info, media


def test_failed_threads_publication_revokes_temporary_permission(monkeypatch, tmp_path: Path) -> None:
    db, group_id, _batch_id, info, media = _threads_batch(tmp_path)
    drive = TemporaryDrive()
    worker = PublicationWorker(db, ThreadsFactory(ThreadsPublisher(fail=True)))
    monkeypatch.setattr(worker, "_load_media", lambda _article_id: (media, drive, group_id, info))
    result = worker.run_once()
    assert result.completed is False
    assert drive.created == [media.file_id]
    assert drive.revoked == [(media.file_id, "temp-permission")]
    assert drive.deleted == []


def test_successful_threads_publication_deletes_file_without_manual_permission_cleanup(
    monkeypatch, tmp_path: Path
) -> None:
    db, group_id, _batch_id, info, media = _threads_batch(tmp_path)
    drive = TemporaryDrive()
    worker = PublicationWorker(db, ThreadsFactory(ThreadsPublisher(fail=False)))
    monkeypatch.setattr(worker, "_load_media", lambda _article_id: (media, drive, group_id, info))
    result = worker.run_once()
    assert result.completed is True
    assert drive.created == [media.file_id]
    assert drive.deleted == [media.file_id]
    assert drive.revoked == []
