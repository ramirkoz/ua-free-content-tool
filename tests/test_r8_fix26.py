from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from content_agent.config import AppConfig
from content_agent.database import Database
from content_agent.models import CollectedArticle
from content_agent.network import NetworkError, _resolve_with_timeout
from content_agent.publishers import PublishContext, PublishResult, Publisher, PublisherFactory
from content_agent.worker import PublicationWorker

UTC = timezone.utc


def _due_database(tmp_path: Path, platform: str = "linkedin") -> tuple[Database, int]:
    db = Database(tmp_path / "fix26.sqlite3")
    source_id = db.add_source("rss", "FIX26", "https://example.com/feed")
    db.insert_collected(
        source_id,
        [CollectedArticle("one", "FIX26 news", "https://example.com/one", "Body", None)],
        enforce_today=False,
    )
    article_id = db.list_articles()[0].id
    batch_id = db.create_batch(
        article_id,
        (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        {platform: "text"},
    )
    return db, batch_id


def test_fix26_bulk_reject_is_atomic(tmp_path: Path) -> None:
    db = Database(tmp_path / "reject.sqlite3")
    source_id = db.add_source("rss", "Bulk", "https://example.com/bulk")
    db.insert_collected(
        source_id,
        [
            CollectedArticle("a", "A", "https://example.com/a", "Body A", None),
            CollectedArticle("b", "B", "https://example.com/b", "Body B", None),
            CollectedArticle("c", "C", "https://example.com/c", "Body C", None),
        ],
        enforce_today=False,
    )
    ids = [group.id for group in db.list_groups()]
    assert len(ids) == 3
    assert db.set_groups_status(ids[:2], "rejected") == 2
    assert {group.id for group in db.list_groups(status="rejected")} == set(ids[:2])
    assert [group.id for group in db.list_groups()] == [ids[2]]


def test_fix26_inbox_ui_supports_bulk_reject_and_delete() -> None:
    source = Path(__file__).parents[1] / "content_agent" / "ui" / "main_window.py"
    text = source.read_text(encoding="utf-8")
    assert 'text="Видалити"' in text
    assert 'text="Запам’ятати й виключати"' in text
    assert 'self.groups_tree.bind("<Delete>", self._delete_selected_group_rows)' in text
    assert "def reject_selected_groups(self) -> None:" in text
    assert "self.db.set_groups_status(group_ids, \"rejected\")" in text
    assert "Автоматичного об’єднання немає" in text


def test_fix26_target_timeout_pauses_batch_and_keeps_database_responsive(tmp_path: Path) -> None:
    db, batch_id = _due_database(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    class BlockingPublisher(Publisher):
        def publish(self, text, progress, context: PublishContext, media=None) -> PublishResult:
            context.before_write()
            entered.set()
            release.wait(3)
            return PublishResult(remote_id="late-success", progress={})

    class Factory(PublisherFactory):
        def __init__(self) -> None:
            super().__init__(AppConfig())

        def create(self, platform: str) -> Publisher:
            return BlockingPublisher()

    worker = PublicationWorker(db, Factory(), target_timeout_seconds=0.15)
    started = time.monotonic()
    result = worker.run_once()
    elapsed = time.monotonic() - started

    assert entered.is_set()
    assert elapsed < 1.0
    assert result.paused is True
    assert "linkedin" in result.failed_platforms
    assert "Результат невідомий" in result.failed_platforms["linkedin"]
    assert db.get_batch(batch_id).status == "paused"
    assert db.get_batch(batch_id).targets[0].status == "failed"
    assert db.list_groups()  # UI reads are not blocked by the external request.
    assert worker.run_once().busy is True

    release.set()
    deadline = time.monotonic() + 2
    while worker._has_inflight_targets() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not worker._has_inflight_targets()
    assert db.get_batch(batch_id).targets[0].status == "failed"


def test_fix26_dns_resolution_has_real_timeout() -> None:
    def slow_resolver(_host: str, _port: int) -> list[str]:
        time.sleep(0.5)
        return ["8.8.8.8"]

    started = time.monotonic()
    try:
        _resolve_with_timeout(slow_resolver, "example.com", 443, 0.05)
    except NetworkError as exc:
        assert "timed out" in str(exc)
    else:
        raise AssertionError("slow DNS resolver unexpectedly completed")
    assert time.monotonic() - started < 0.3


def test_fix26_worker_logs_package_and_target_context() -> None:
    source = Path(__file__).parents[1] / "content_agent" / "worker.py"
    text = source.read_text(encoding="utf-8")
    assert "Пакет #{batch.id}, ціль #{target.id}" in text
    assert "outcome_unknown=True" in text
    assert "Do not hold DATA_MAINTENANCE_LOCK during external HTTP calls" in text
