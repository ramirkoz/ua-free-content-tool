from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from content_agent.config import AppConfig
from content_agent.database import Database
from content_agent.google_drive import GoogleDriveError
from content_agent.models import CollectedArticle, MediaPayload
from content_agent.publishers import PublishContext, PublishResult, Publisher, PublisherFactory
from content_agent.worker import PublicationWorker

UTC = timezone.utc


class OkPublisher(Publisher):
    def __init__(self) -> None:
        self.calls = 0

    def publish(self, text, progress, context: PublishContext, media=None):
        self.calls += 1
        context.before_write()
        return PublishResult(remote_id=f"ok-{self.calls}", progress={})


class Factory(PublisherFactory):
    def __init__(self, publisher: Publisher):
        super().__init__(AppConfig())
        self.publisher = publisher

    def create(self, platform: str) -> Publisher:
        return self.publisher


class BrokenDeleteDrive:
    def delete_file(self, _file_id: str) -> None:
        raise GoogleDriveError("Drive cleanup unavailable")


def build_media_batch(tmp_path: Path, targets: dict[str, str] | None = None):
    db = Database(tmp_path / "queue.sqlite3")
    source = db.add_source("rss", "Source", "https://example.com/feed")
    db.insert_collected(
        source,
        [CollectedArticle("a", "Новина", "https://example.com/a", "Повний текст", None)],
        enforce_today=False,
    )
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
    batch_id = db.create_batch(
        db.lead_article_id(group.id),
        (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        targets or {"telegram": "text"},
    )
    media = MediaPayload(
        file_id="1AbCdEfGhIjKlMnOpQrStUvWxYz_12345",
        name="photo.jpg",
        kind="image",
        mime_type="image/jpeg",
        data=b"image",
        public_url="https://drive.example/media",
    )
    return db, group.id, batch_id, media


def force_due(db: Database, batch_id: int) -> None:
    with db.connect() as connection:
        connection.execute(
            "UPDATE publication_batches SET scheduled_at=? WHERE id=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), batch_id),
        )


def test_drive_preflight_failure_is_bounded_and_pauses_after_three(tmp_path: Path, monkeypatch) -> None:
    db, _group_id, batch_id, _media = build_media_batch(tmp_path)
    worker = PublicationWorker(db, Factory(OkPublisher()), max_automatic_attempts=3)
    monkeypatch.setattr(worker, "_load_media", lambda _article_id: (_ for _ in ()).throw(GoogleDriveError("Drive offline")))

    for expected_attempt in (1, 2, 3):
        result = worker.run_once()
        batch = db.get_batch(batch_id)
        assert batch.attempts == expected_attempt
        assert result.claimed is True
        if expected_attempt < 3:
            assert batch.status == "pending"
            force_due(db, batch_id)
        else:
            assert batch.status == "paused"
            assert result.paused is True

    # A paused poisoned package is not reclaimed and attempts cannot run away to 300.
    assert worker.run_once().claimed is False
    assert db.get_batch(batch_id).attempts == 3


def test_restart_pauses_abandoned_and_exhausted_batches(tmp_path: Path) -> None:
    db, _group_id, batch_id, _media = build_media_batch(tmp_path)
    claimed = db.claim_due_batch(owner="dead-process", lease_seconds=999)
    assert claimed and claimed.id == batch_id
    with db.connect() as connection:
        connection.execute("UPDATE publication_batches SET attempts=300 WHERE id=?", (batch_id,))

    recovered = db.recover_abandoned_batches(max_automatic_attempts=3)
    assert recovered == [batch_id]
    batch = db.get_batch(batch_id)
    assert batch.status == "paused"
    assert batch.lease_owner is None
    assert batch.attempts == 300


def test_user_can_cooperatively_cancel_during_drive_preflight(tmp_path: Path, monkeypatch) -> None:
    db, group_id, batch_id, media = build_media_batch(tmp_path)
    publisher = OkPublisher()
    worker = PublicationWorker(
        db,
        Factory(publisher),
        media_preflight_timeout_seconds=5,
    )

    def slow_media(_article_id):
        time.sleep(2.0)
        return media, BrokenDeleteDrive(), group_id, None

    monkeypatch.setattr(worker, "_load_media", slow_media)
    holder = []
    thread = threading.Thread(target=lambda: holder.append(worker.run_once()), daemon=True)
    thread.start()

    deadline = time.monotonic() + 2
    while worker.active_batch_id() != batch_id and time.monotonic() < deadline:
        time.sleep(0.01)
    assert worker.active_batch_id() == batch_id
    assert worker.request_cancel(batch_id) is True
    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert db.get_batch(batch_id).status == "cancelled"
    assert publisher.calls == 0


def test_cleanup_drive_failure_is_bounded(tmp_path: Path, monkeypatch) -> None:
    db, group_id, batch_id, media = build_media_batch(tmp_path)
    publisher = OkPublisher()
    broken = BrokenDeleteDrive()
    worker = PublicationWorker(db, Factory(publisher), max_automatic_attempts=3)
    monkeypatch.setattr(worker, "_load_media", lambda _article_id: (media, broken, group_id, None))
    monkeypatch.setattr(worker, "_drive_client", lambda: broken)

    first = worker.run_once()
    assert first.claimed is True
    assert db.get_batch(batch_id).status == "pending"
    assert db.get_batch(batch_id).attempts == 1
    assert publisher.calls == 1

    for expected in (2, 3):
        force_due(db, batch_id)
        worker.run_once()
        batch = db.get_batch(batch_id)
        assert batch.attempts == expected
    assert db.get_batch(batch_id).status == "paused"
    # Sent target never gets re-published during cleanup retries.
    assert publisher.calls == 1


def test_cancel_after_first_platform_write_stops_remaining_targets(tmp_path: Path, monkeypatch) -> None:
    db, group_id, batch_id, media = build_media_batch(
        tmp_path, {"facebook:1": "one", "telegram": "two"}
    )

    started = threading.Event()
    release = threading.Event()

    class BlockingPublisher(Publisher):
        def __init__(self):
            self.calls = 0
        def publish(self, text, progress, context: PublishContext, media=None):
            self.calls += 1
            context.before_write()
            if self.calls == 1:
                started.set()
                release.wait(2)
            return PublishResult(remote_id=f"remote-{self.calls}", progress={})

    publisher = BlockingPublisher()
    worker = PublicationWorker(db, Factory(publisher), inter_target_delay_seconds=0)
    monkeypatch.setattr(worker, "_load_media", lambda _article_id: (media, BrokenDeleteDrive(), group_id, None))

    holder = []
    thread = threading.Thread(target=lambda: holder.append(worker.run_once()), daemon=True)
    thread.start()
    assert started.wait(1)
    assert worker.request_cancel(batch_id) is True
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    batch = db.get_batch(batch_id)
    assert batch.status == "cancelled"
    assert publisher.calls == 1
    statuses = {target.platform: target.status for target in batch.targets}
    assert list(statuses.values()).count("sent") == 1
    assert list(statuses.values()).count("pending") == 1
