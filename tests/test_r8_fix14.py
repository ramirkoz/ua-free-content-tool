from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from content_agent.config import AppConfig
from content_agent.database import Database
from content_agent.models import CollectedArticle
from content_agent.publishers import PublishContext, PublishError, PublishResult, Publisher, PublisherFactory, _check_payload
from content_agent.worker import PublicationWorker

UTC = timezone.utc


def _database_with_batch(tmp_path: Path) -> tuple[Database, int]:
    db = Database(tmp_path / "fix14.sqlite3")
    source_id = db.add_source("rss", "FIX14", "https://example.com/feed")
    db.insert_collected(
        source_id,
        [CollectedArticle("fix14", "FIX14", "https://example.com/fix14", "Body", None)],
        enforce_today=False,
    )
    article_id = db.list_articles()[0].id
    batch_id = db.create_batch(
        article_id,
        (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        {"threads": "threads", "telegram": "telegram", "facebook:1": "facebook"},
    )
    return db, batch_id


class _OutcomePublisher(Publisher):
    def __init__(self, platform: str) -> None:
        self.platform = platform

    def publish(self, text, progress, context: PublishContext, media=None) -> PublishResult:
        context.before_write()
        if self.platform == "telegram":
            raise PublishError("Telegram: chat not found (код 400)")
        if self.platform == "facebook:1":
            raise PublishError("Invalid OAuth access token")
        return PublishResult(remote_id="threads-ok", progress={})


class _OutcomeFactory(PublisherFactory):
    def __init__(self) -> None:
        super().__init__(AppConfig())

    def create(self, platform: str) -> Publisher:
        return _OutcomePublisher(platform)


def test_partial_publication_keeps_errors_visible_and_reports_outcomes(tmp_path: Path) -> None:
    db, batch_id = _database_with_batch(tmp_path)
    result = PublicationWorker(db, _OutcomeFactory()).run_once()
    assert result.claimed is True
    assert result.completed is False
    assert result.sent_platforms == ["threads"]
    assert result.failed_platforms == {
        "telegram": "Telegram: chat not found (код 400)",
        "facebook:1": "Invalid OAuth access token",
    }
    batch = db.get_batch(batch_id)
    statuses = {target.platform: target.status for target in batch.targets}
    assert statuses == {"threads": "sent", "telegram": "failed", "facebook:1": "failed"}
    errors = {target.platform: target.last_error for target in batch.targets}
    assert errors["telegram"] == "Telegram: chat not found (код 400)"
    assert errors["facebook:1"] == "Invalid OAuth access token"
    assert batch.status == "pending"


def test_retry_does_not_duplicate_successful_target(tmp_path: Path) -> None:
    db, batch_id = _database_with_batch(tmp_path)
    first = PublicationWorker(db, _OutcomeFactory()).run_once()
    assert first.sent_platforms == ["threads"]
    with db.connect() as connection:
        connection.execute(
            "UPDATE publication_batches SET scheduled_at=? WHERE id=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), batch_id),
        )

    calls: list[str] = []

    class _RetryPublisher(Publisher):
        def __init__(self, platform: str) -> None:
            self.platform = platform

        def publish(self, text, progress, context: PublishContext, media=None) -> PublishResult:
            context.before_write()
            calls.append(self.platform)
            return PublishResult(remote_id=f"ok-{self.platform}", progress={})

    class _RetryFactory(PublisherFactory):
        def __init__(self) -> None:
            super().__init__(AppConfig())

        def create(self, platform: str) -> Publisher:
            return _RetryPublisher(platform)

    second = PublicationWorker(db, _RetryFactory()).run_once()
    assert second.completed is True
    assert set(calls) == {"telegram", "facebook:1"}
    assert "threads" not in second.sent_platforms


def test_telegram_error_description_is_not_lost() -> None:
    with pytest.raises(PublishError, match=r"Telegram: Bad Request: chat not found \(код 400\)"):
        _check_payload({"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})


def test_fix14_ui_contains_per_target_error_and_result_dialog() -> None:
    source = Path("content_agent/ui/main_window.py").read_text(encoding="utf-8")
    assert 'root.title("UA FREE Content Tool — v1.1.2")' in source
    assert 'item.status == "failed" and item.last_error' in source
    assert "Не опубліковано:" in source
    assert "Успішні публікації не дублюватимуться" in source
