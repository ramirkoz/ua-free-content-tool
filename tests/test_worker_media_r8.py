from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from content_agent.config import AppConfig
from content_agent.database import Database
from content_agent.models import CollectedArticle, MediaPayload
from content_agent.publishers import PublishContext, PublishError, PublishResult, Publisher, PublisherFactory
from content_agent.scheduling import KYIV
from content_agent.worker import PublicationWorker


class MediaPublisher(Publisher):
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.seen_media = False

    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media: MediaPayload | None = None) -> PublishResult:
        context.before_write()
        self.seen_media = media is not None and media.data == b"image"
        if self.fail:
            raise PublishError("temporary")
        return PublishResult(remote_id="ok", progress={})


class MediaFactory(PublisherFactory):
    def __init__(self, publisher: MediaPublisher):
        super().__init__(AppConfig())
        self.publisher = publisher

    def create(self, platform: str) -> Publisher:
        return self.publisher


class FakeDrive:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_file(self, file_id: str) -> None:
        self.deleted.append(file_id)


def _batch(tmp_path: Path) -> tuple[Database, int, int]:
    db = Database(tmp_path / "db.sqlite3")
    source = db.add_source("rss", "Source", "https://example.com/feed")
    db.insert_collected(source, [CollectedArticle(
        "a", "Новина", "https://example.com/a", "Повний текст новини", datetime.now(KYIV).isoformat()
    )])
    group = db.get_group(db.list_groups()[0].id)
    db.set_group_media(
        group.id,
        drive_url="https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz_12345/view",
        file_id="1AbCdEfGhIjKlMnOpQrStUvWxYz_12345",
        name="photo.jpg",
        kind="image",
        mime="image/jpeg",
        size=5,
    )
    batch = db.create_batch(
        db.lead_article_id(group.id),
        (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        {"telegram": "text"},
    )
    return db, group.id, batch


def test_media_is_permanently_deleted_only_after_success(monkeypatch, tmp_path: Path) -> None:
    db, group_id, batch_id = _batch(tmp_path)
    publisher = MediaPublisher()
    drive = FakeDrive()
    worker = PublicationWorker(db, MediaFactory(publisher))
    media = MediaPayload(
        file_id="1AbCdEfGhIjKlMnOpQrStUvWxYz_12345",
        name="photo.jpg",
        kind="image",
        mime_type="image/jpeg",
        data=b"image",
        public_url="https://drive.usercontent.google.com/download?id=1",
    )
    monkeypatch.setattr(worker, "_load_media", lambda _article_id: (media, drive, group_id, None))
    result = worker.run_once()
    assert result.completed is True
    assert publisher.seen_media is True
    assert drive.deleted == [media.file_id]
    assert db.get_group(group_id).media_file_id == ""
    assert db.get_batch(batch_id).status == "completed"


def test_media_is_retained_when_publication_fails(monkeypatch, tmp_path: Path) -> None:
    db, group_id, _batch_id = _batch(tmp_path)
    publisher = MediaPublisher(fail=True)
    drive = FakeDrive()
    worker = PublicationWorker(db, MediaFactory(publisher))
    media = MediaPayload(
        file_id="1AbCdEfGhIjKlMnOpQrStUvWxYz_12345",
        name="photo.jpg",
        kind="image",
        mime_type="image/jpeg",
        data=b"image",
        public_url="https://drive.usercontent.google.com/download?id=1",
    )
    monkeypatch.setattr(worker, "_load_media", lambda _article_id: (media, drive, group_id, None))
    result = worker.run_once()
    assert result.completed is False
    assert drive.deleted == []
    assert db.get_group(group_id).media_file_id == media.file_id
