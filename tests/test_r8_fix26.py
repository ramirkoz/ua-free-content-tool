from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from content_agent.config import AppConfig
from content_agent.database import Database
from content_agent.models import PublishResult
from content_agent.platforms import PublishContext, Publisher, PublisherFactory
from content_agent.worker import PublicationWorker


def _due_database(tmp_path: Path) -> tuple[Database, int]:
    db = Database(tmp_path / "content.sqlite3")
    source_id = db.add_source("rss", "Source", "https://example.com/feed")
    db.insert_collected(
        source_id,
        [
            {
                "external_id": "one",
                "title": "Title",
                "url": "https://example.com/one",
                "raw_text": "Body",
                "published_at": None,
            }
        ],
        enforce_today=False,
    )
    group = db.list_groups()[0]
    db.save_group_rewrite(
        group.id,
        headline="Headline",
        fact_card="Facts",
        rewrite_text="Publication text",
        platform_texts={"linkedin": "Publication text"},
    )
    batch_id = db.queue_targets(
        db.lead_article_id(group.id),
        "2020-01-01T00:00:00+00:00",
        {"linkedin": "Publication text"},
    ).batch_id
    return db, batch_id


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
    # The publisher blocks for three seconds. A 1.5-second ceiling still proves
    # that run_once returns without waiting for it, while tolerating hosted
    # Windows runner scheduling jitter observed around the former 1.0-second cap.
    assert elapsed < 1.5
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


def test_fix26_existing_schema_rejects_duplicate_remote_ids(tmp_path: Path) -> None:
    db, batch_id = _due_database(tmp_path)
    target = db.get_batch(batch_id).targets[0]
    with db.connect() as connection:
        connection.execute(
            "UPDATE publication_targets SET status='sent',remote_id='remote-one' WHERE id=?",
            (target.id,),
        )
        connection.execute(
            "INSERT INTO publication_targets(batch_id,platform,status,attempts,remote_id,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (batch_id, "telegram", "sent", 1, "remote-two", "2020-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00"),
        )
        with sqlite3.connect(db.path) as separate:
            separate.execute("PRAGMA busy_timeout=100")
            try:
                separate.execute(
                    "UPDATE publication_targets SET remote_id='remote-one' WHERE platform='telegram'"
                )
                separate.commit()
            except sqlite3.IntegrityError:
                pass
            else:  # pragma: no cover - indicates a missing release gate.
                raise AssertionError("duplicate remote IDs were accepted")


def test_fix26_progress_json_remains_valid_after_timeout(tmp_path: Path) -> None:
    db, batch_id = _due_database(tmp_path)
    target = db.get_batch(batch_id).targets[0]
    with db.connect() as connection:
        connection.execute(
            "UPDATE publication_targets SET progress_json=? WHERE id=?",
            (json.dumps({"step": "started", "attempt": 1}), target.id),
        )
    refreshed = db.get_batch(batch_id).targets[0]
    assert refreshed.progress == {"step": "started", "attempt": 1}
