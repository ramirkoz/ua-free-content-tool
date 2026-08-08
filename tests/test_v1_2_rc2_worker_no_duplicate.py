from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from content_agent.config import AppConfig
from content_agent.database import Database
from content_agent.models import CollectedArticle
from content_agent.network import NetworkError
from content_agent.publishers import Publisher, PublisherFactory
from content_agent.safe_publishers_v1_2 import SafeLinkedInPublisher
from content_agent.worker import PublicationWorker


class _SafeLinkedInFactory(PublisherFactory):
    def __init__(self) -> None:
        super().__init__(AppConfig())

    def create(self, platform: str) -> Publisher:
        assert platform == "linkedin"
        return SafeLinkedInPublisher("urn:li:person:test", "token", "202601")


def test_worker_never_reposts_linkedin_after_ambiguous_first_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database(tmp_path / "db.sqlite3")
    source_id = db.add_source("rss", "s", "https://example.com/feed")
    db.insert_collected(
        source_id,
        [CollectedArticle("x", "title", "https://example.com/x", "body", None)],
        enforce_today=False,
    )
    article_id = db.list_articles()[0].id
    batch_id = db.create_batch(
        article_id,
        (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        {"linkedin": "same text"},
    )

    calls = 0

    def ambiguous_post(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        raise NetworkError("socket closed after request was sent")

    monkeypatch.setattr("content_agent.safe_publishers_v1_2._linkedin_post_json", ambiguous_post)
    worker = PublicationWorker(
        db,
        _SafeLinkedInFactory(),
        lease_seconds=60,
        max_automatic_attempts=3,
    )

    first = worker.run_once()
    assert first.paused is True
    assert calls == 1
    target = db.get_batch(batch_id).targets[0]
    assert target.progress["linkedin_write_started"] is True
    assert target.progress["linkedin_write_completed"] is False

    db.resume_batch(batch_id)
    second = worker.run_once()
    assert second.paused is True
    assert calls == 1, "resume after an ambiguous LinkedIn write must not issue another POST"
