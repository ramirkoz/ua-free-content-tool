from __future__ import annotations

from pathlib import Path

import pytest

from content_agent.config import AppConfig
from content_agent.database import Database
from content_agent.models import CollectedArticle
from content_agent.publishers import PublishContext, PublishError, PublishResult, Publisher, PublisherFactory, TelegramBotPublisher, ThreadsPublisher
from content_agent.worker import PublicationWorker


def test_threads_resumes_existing_container(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_post(url: str, fields: dict[str, object]) -> dict[str, object]:
        calls.append(url)
        return {"id": "published-1"}

    monkeypatch.setattr("content_agent.publishers._post_form", fake_post)
    publisher = ThreadsPublisher("user", "token")
    saved: list[dict[str, object]] = []
    result = publisher.publish(
        "text",
        {"container_id": "container-1"},
        PublishContext(before_write=lambda: None, save_progress=saved.append),
    )
    assert result.remote_id == "published-1"
    assert len(calls) == 1
    assert calls[0].endswith("/threads_publish")
    assert saved[-1]["published_parts"] == 1
    assert saved[-1]["remote_ids"] == ["published-1"]


def test_telegram_resumes_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_post(url: str, fields: dict[str, object]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"ok": True, "result": {"message_id": calls}}

    monkeypatch.setattr("content_agent.publishers._post_form", fake_post)
    publisher = TelegramBotPublisher("123456:abcdefghijklmnopqrstuvwxyz", "@channel")
    text = "a" * 4500
    result = publisher.publish(
        text,
        {"sent_parts": 1, "remote_ids": ["old"]},
        PublishContext(before_write=lambda: None, save_progress=lambda _p: None),
    )
    assert calls == 1
    assert result.progress["sent_parts"] == 2


class _FakePublisher(Publisher):
    def __init__(self, platform: str, failures: dict[str, int], calls: list[str]):
        self.platform = platform
        self.failures = failures
        self.calls = calls

    def publish(self, text: str, progress: dict[str, object], context: PublishContext) -> PublishResult:
        context.before_write()
        self.calls.append(self.platform)
        if self.failures.get(self.platform, 0):
            self.failures[self.platform] -= 1
            raise PublishError("temporary")
        return PublishResult(remote_id=f"remote-{self.platform}", progress={})


class _FakeFactory(PublisherFactory):
    def __init__(self, failures: dict[str, int], calls: list[str]):
        super().__init__(AppConfig())
        self.failures = failures
        self.calls = calls

    def create(self, platform: str) -> Publisher:
        return _FakePublisher(platform, self.failures, self.calls)


def test_worker_retries_only_failed_target(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite3")
    source_id = db.add_source("rss", "s", "https://example.com/feed")
    db.insert_collected(source_id, [CollectedArticle("x", "t", "https://example.com/x", "body", None)], enforce_today=False)
    article_id = db.list_articles()[0].id
    from datetime import datetime, timedelta, timezone

    db.create_batch(
        article_id,
        (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        {"facebook:1": "a", "facebook:2": "b"},
    )
    calls: list[str] = []
    failures = {"facebook:2": 1}
    worker = PublicationWorker(db, _FakeFactory(failures, calls), lease_seconds=60)
    first = worker.run_once()
    assert first.completed is False
    assert calls == ["facebook:1", "facebook:2"]
    # Make the retry due immediately.
    with db.connect() as connection:
        connection.execute("UPDATE publication_batches SET scheduled_at='2000-01-01T00:00:00+00:00' WHERE status='pending'")
    second = worker.run_once()
    assert second.completed is True
    assert calls == ["facebook:1", "facebook:2", "facebook:2"]


def test_worker_does_not_hold_maintenance_lock_during_external_publish(tmp_path: Path) -> None:
    import threading
    import time
    from content_agent.maintenance import DATA_MAINTENANCE_LOCK

    db = Database(tmp_path / "db-lock.sqlite3")
    source_id = db.add_source("rss", "s", "https://example.com/feed")
    db.insert_collected(source_id, [CollectedArticle("lock", "t", "https://example.com/lock", "body", None)], enforce_today=False)
    article_id = db.list_articles()[0].id
    from datetime import datetime, timedelta, timezone

    db.create_batch(
        article_id,
        (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        {"telegram": "payload"},
    )

    entered_publish = threading.Event()
    release_publish = threading.Event()
    acquired_maintenance = threading.Event()

    class BlockingPublisher(Publisher):
        def publish(self, text: str, progress: dict[str, object], context: PublishContext) -> PublishResult:
            context.before_write()
            entered_publish.set()
            assert release_publish.wait(3)
            return PublishResult(remote_id="remote", progress={})

    class BlockingFactory(_FakeFactory):
        def __init__(self) -> None:
            super().__init__({}, [])

        def create(self, platform: str) -> Publisher:
            return BlockingPublisher()

    worker = PublicationWorker(db, BlockingFactory(), lease_seconds=60)
    worker_thread = threading.Thread(target=worker.run_once)
    worker_thread.start()
    assert entered_publish.wait(2)

    def acquire_lock() -> None:
        with DATA_MAINTENANCE_LOCK:
            acquired_maintenance.set()

    maintenance_thread = threading.Thread(target=acquire_lock)
    maintenance_thread.start()
    assert acquired_maintenance.wait(1.0)
    # UI/database reads remain available while the network call is still waiting.
    assert db.list_groups()
    release_publish.set()
    worker_thread.join(3)
    maintenance_thread.join(3)
    assert acquired_maintenance.is_set()
