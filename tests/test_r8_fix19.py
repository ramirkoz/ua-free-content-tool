from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import content_agent.worker as worker_module
from content_agent.config import AppConfig
from content_agent.database import Database
from content_agent.models import CollectedArticle
from content_agent.publishers import (
    PublishContext,
    PublishError,
    PublishResult,
    Publisher,
    PublisherFactory,
    _check_payload,
)
from content_agent.worker import PublicationWorker

UTC = timezone.utc


def _due_database(tmp_path: Path, targets: dict[str, str], suffix: str = "one") -> tuple[Database, int]:
    db = Database(tmp_path / f"fix20-{suffix}.sqlite3")
    source_id = db.add_source("rss", f"FIX20 {suffix}", f"https://example.com/{suffix}.xml")
    db.insert_collected(
        source_id,
        [CollectedArticle(f"fix20-{suffix}", f"FIX20 {suffix}", f"https://example.com/{suffix}", "Body", None)],
        enforce_today=False,
    )
    article_id = db.list_articles()[0].id
    batch_id = db.create_batch(
        article_id,
        (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        targets,
    )
    return db, batch_id


class _RecordingPublisher(Publisher):
    def __init__(self, platform: str, calls: list[str]) -> None:
        self.platform = platform
        self.calls = calls

    def publish(self, text, progress, context: PublishContext, media=None) -> PublishResult:
        context.before_write()
        self.calls.append(self.platform)
        return PublishResult(remote_id=f"ok-{self.platform}", progress={})


class _RecordingFactory(PublisherFactory):
    def __init__(self, config: AppConfig, calls: list[str]) -> None:
        super().__init__(config)
        self.calls = calls

    def create(self, platform: str) -> Publisher:
        return _RecordingPublisher(platform, self.calls)


def test_fix20_publishes_strictly_in_order_with_five_second_gaps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    targets = {
        "telegram": "telegram",
        "facebook:p1": "p1",
        "linkedin": "linkedin",
        "threads": "threads",
        "facebook:p2": "p2",
    }
    db, _batch_id = _due_database(tmp_path, targets, "order")
    config = AppConfig(
        facebook_pages=[
            {"id": "p2", "name": "Page 2", "access_token": "token-2"},
            {"id": "p1", "name": "Page 1", "access_token": "token-1"},
        ]
    )
    calls: list[str] = []
    sleeps: list[float] = []
    progress: list[str] = []
    monkeypatch.setattr(worker_module.time, "sleep", lambda value: sleeps.append(float(value)))

    result = PublicationWorker(
        db,
        _RecordingFactory(config, calls),
        inter_target_delay_seconds=5.0,
        progress_callback=progress.append,
    ).run_once()

    assert result.completed is True
    assert calls == ["facebook:p2", "facebook:p1", "threads", "linkedin", "telegram"]
    # Four inter-target pauses, each counted down as five one-second slices.
    assert sleeps == [1.0] * 20
    assert sum("Пауза перед наступною платформою" in item for item in progress) == 20


def test_fix20_single_flight_blocks_manual_and_background_overlap(tmp_path: Path) -> None:
    db, _batch_id = _due_database(tmp_path, {"threads": "text"}, "single-flight")
    entered = threading.Event()
    release = threading.Event()

    class _BlockingPublisher(Publisher):
        def publish(self, text, progress, context: PublishContext, media=None) -> PublishResult:
            context.before_write()
            entered.set()
            assert release.wait(5)
            return PublishResult(remote_id="ok", progress={})

    class _Factory(PublisherFactory):
        def __init__(self) -> None:
            super().__init__(AppConfig())

        def create(self, platform: str) -> Publisher:
            return _BlockingPublisher()

    worker = PublicationWorker(db, _Factory())
    first_result: list[object] = []
    thread = threading.Thread(target=lambda: first_result.append(worker.run_once()), daemon=True)
    thread.start()
    assert entered.wait(2)

    second = worker.run_once()
    assert second.claimed is False
    assert second.busy is True

    release.set()
    thread.join(5)
    assert first_result and first_result[0].completed is True


def test_fix20_auth_failure_pauses_and_resume_retries_only_unsent(tmp_path: Path) -> None:
    db, batch_id = _due_database(tmp_path, {"threads": "threads", "telegram": "telegram"}, "auth")
    first_calls: list[str] = []

    class _FirstPublisher(Publisher):
        def __init__(self, platform: str) -> None:
            self.platform = platform

        def publish(self, text, progress, context: PublishContext, media=None) -> PublishResult:
            context.before_write()
            first_calls.append(self.platform)
            if self.platform == "threads":
                raise PublishError(
                    "Error validating access token (код 190)",
                    code=190,
                    retryable=False,
                    auth_error=True,
                )
            return PublishResult(remote_id="telegram-ok", progress={})

    class _FirstFactory(PublisherFactory):
        def __init__(self) -> None:
            super().__init__(AppConfig())

        def create(self, platform: str) -> Publisher:
            return _FirstPublisher(platform)

    first = PublicationWorker(db, _FirstFactory()).run_once()
    assert first.paused is True
    assert first.auth_failed_platforms == ["threads"]
    assert first_calls == ["threads", "telegram"]
    batch = db.get_batch(batch_id)
    assert batch.status == "paused"
    assert {target.platform: target.status for target in batch.targets} == {
        "telegram": "sent",
        "threads": "failed",
    }
    assert db.claim_due_batch(owner="should-not-claim") is None

    db.resume_batch(batch_id)
    retry_calls: list[str] = []
    second = PublicationWorker(db, _RecordingFactory(AppConfig(), retry_calls)).run_once()
    assert second.completed is True
    assert retry_calls == ["threads"]
    assert "telegram" not in second.sent_platforms


def test_fix20_missing_token_is_captured_and_does_not_retry_every_second(tmp_path: Path) -> None:
    db, batch_id = _due_database(tmp_path, {"threads": "text"}, "missing-token")
    # Real factory construction raises before any HTTP request. FIX18 allowed that
    # exception to escape the target handler and made the batch due again immediately.
    result = PublicationWorker(db, PublisherFactory(AppConfig())).run_once()
    assert result.claimed is True
    assert result.paused is True
    assert "threads" in result.failed_platforms
    batch = db.get_batch(batch_id)
    assert batch.status == "paused"
    assert batch.attempts == 1
    assert db.claim_due_batch(owner="no-storm") is None


def test_fix20_transient_failures_stop_after_three_automatic_attempts(tmp_path: Path) -> None:
    db, batch_id = _due_database(tmp_path, {"telegram": "text"}, "max-attempts")

    class _TransientPublisher(Publisher):
        def publish(self, text, progress, context: PublishContext, media=None) -> PublishResult:
            context.before_write()
            raise PublishError("Temporary service failure", retryable=True)

    class _Factory(PublisherFactory):
        def __init__(self) -> None:
            super().__init__(AppConfig())

        def create(self, platform: str) -> Publisher:
            return _TransientPublisher()

    worker = PublicationWorker(db, _Factory(), max_automatic_attempts=3)
    for expected_attempt in (1, 2, 3):
        result = worker.run_once()
        assert result.claimed is True
        batch = db.get_batch(batch_id)
        assert batch.attempts == expected_attempt
        if expected_attempt < 3:
            assert batch.status == "pending"
            with db.connect() as connection:
                connection.execute(
                    "UPDATE publication_batches SET scheduled_at=? WHERE id=?",
                    ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), batch_id),
                )
        else:
            assert result.paused is True
            assert batch.status == "paused"
    assert db.claim_due_batch(owner="no-forty-attempts") is None


def test_fix20_meta_error_classification() -> None:
    with pytest.raises(PublishError) as auth_info:
        _check_payload(
            {"error": {"message": "Invalid OAuth access token", "code": 190, "error_subcode": 463}},
            http_status=400,
        )
    assert auth_info.value.auth_error is True
    assert auth_info.value.retryable is False
    assert auth_info.value.code == 190

    with pytest.raises(PublishError) as rate_info:
        _check_payload(
            {"error": {"message": "Calls to this API have exceeded the rate limit", "code": 613}},
            http_status=429,
        )
    assert rate_info.value.rate_limited is True
    assert rate_info.value.retryable is True


def test_fix20_ui_contract_exposes_pacing_pause_and_manual_resume() -> None:
    source = Path("content_agent/ui/main_window.py").read_text(encoding="utf-8")
    assert 'root.title("UA FREE Content Tool — R8 FIX30")' in source
    assert "inter_target_delay_seconds=5.0" in source
    assert '"Призупинені": {"paused"}' in source
    assert 'text="Повторити невідправлені"' in source
    assert "Інша публікація вже виконується" in source


def test_fix20_schema3_queue_migrates_to_paused_without_losing_targets(tmp_path: Path) -> None:
    path = tmp_path / "schema3.sqlite3"
    db = Database(path)
    source_id = db.add_source("rss", "Schema 3", "https://example.com/schema3.xml")
    db.insert_collected(
        source_id,
        [CollectedArticle("schema3", "Schema 3", "https://example.com/schema3", "Body", None)],
        enforce_today=False,
    )
    article_id = db.list_articles()[0].id
    batch_id = db.create_batch(
        article_id,
        (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        {"threads": "text"},
    )

    # Simulate the exact FIX18 queue constraint and schema version.
    con = __import__("sqlite3").connect(path)
    try:
        con.execute("PRAGMA foreign_keys=OFF")
        con.executescript(
            """
            DROP INDEX IF EXISTS idx_batches_due;
            DROP INDEX IF EXISTS idx_batches_article;
            CREATE TABLE publication_batches_old (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                scheduled_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','in_progress','completed','cancelled')),
                lease_owner TEXT,
                lease_until TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                cleanup_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO publication_batches_old
            SELECT * FROM publication_batches;
            DROP TABLE publication_batches;
            ALTER TABLE publication_batches_old RENAME TO publication_batches;
            CREATE INDEX idx_batches_due ON publication_batches(status,scheduled_at,lease_until);
            CREATE INDEX idx_batches_article ON publication_batches(article_id,status);
            PRAGMA user_version=3;
            """
        )
        con.commit()
    finally:
        con.close()

    migrated = Database(path)
    batch = migrated.get_batch(batch_id)
    assert batch.status == "pending"
    assert [target.platform for target in batch.targets] == ["threads"]
    with migrated.connect() as connection:
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='publication_batches'"
        ).fetchone()[0]
        assert "'paused'" in sql
        assert connection.execute("PRAGMA foreign_key_check").fetchone() is None


def test_fix20_meta_rate_limit_stops_further_meta_calls_in_same_pass(tmp_path: Path) -> None:
    db, batch_id = _due_database(
        tmp_path,
        {
            "facebook:p1": "one",
            "facebook:p2": "two",
            "threads": "threads",
            "linkedin": "linkedin",
            "telegram": "telegram",
        },
        "meta-limit",
    )
    calls: list[str] = []
    config = AppConfig(
        facebook_pages=[
            {"id": "p1", "name": "One", "access_token": "t1"},
            {"id": "p2", "name": "Two", "access_token": "t2"},
        ]
    )

    class _Publisher(Publisher):
        def __init__(self, platform: str) -> None:
            self.platform = platform

        def publish(self, text, progress, context: PublishContext, media=None) -> PublishResult:
            context.before_write()
            calls.append(self.platform)
            if self.platform == "facebook:p1":
                raise PublishError(
                    "Calls to this API have exceeded the rate limit (код 613)",
                    code=613,
                    retryable=True,
                    rate_limited=True,
                )
            return PublishResult(remote_id=f"ok-{self.platform}", progress={})

    class _Factory(PublisherFactory):
        def __init__(self) -> None:
            super().__init__(config)

        def create(self, platform: str) -> Publisher:
            return _Publisher(platform)

    result = PublicationWorker(db, _Factory()).run_once()
    assert calls == ["facebook:p1", "linkedin", "telegram"]
    assert "facebook:p2" in result.failed_platforms
    assert "threads" in result.failed_platforms
    batch = db.get_batch(batch_id)
    statuses = {target.platform: target.status for target in batch.targets}
    assert statuses["linkedin"] == "sent"
    assert statuses["telegram"] == "sent"
    assert statuses["facebook:p1"] == "failed"
    assert statuses["facebook:p2"] == "failed"
    assert statuses["threads"] == "failed"
    assert batch.status == "pending"
