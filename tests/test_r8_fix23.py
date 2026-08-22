from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import content_agent.platform_setup as setup
from content_agent.config import AppConfig
from content_agent.database import Database
from content_agent.models import CollectedArticle
from content_agent.publishers import PublishContext, PublishError, PublishResult, Publisher, PublisherFactory
from content_agent.worker import PublicationWorker

UTC = timezone.utc


def _add_due_batch(db: Database, suffix: str, targets: dict[str, str]) -> int:
    source_id = db.add_source("rss", f"FIX23 {suffix}", f"https://example.com/{suffix}.xml")
    db.insert_collected(
        source_id,
        [CollectedArticle(f"fix23-{suffix}", f"FIX23 {suffix}", f"https://example.com/{suffix}", "Body", None)],
        enforce_today=False,
    )
    article = next(item for item in db.list_articles() if item.title == f"FIX23 {suffix}")
    return db.create_batch(
        article.id,
        (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        targets,
    )


def test_fix23_auth_circuit_breaker_stops_cross_package_meta_storm(tmp_path: Path) -> None:
    db = Database(tmp_path / "breaker.sqlite3")
    first_id = _add_due_batch(db, "first", {"facebook:p1": "fb1", "telegram": "tg1"})
    second_id = _add_due_batch(db, "second", {"facebook:p1": "fb2", "telegram": "tg2"})
    calls: list[str] = []

    class _Publisher(Publisher):
        def __init__(self, platform: str) -> None:
            self.platform = platform

        def publish(self, text, progress, context: PublishContext, media=None) -> PublishResult:
            context.before_write()
            calls.append(self.platform)
            if self.platform.startswith("facebook:"):
                raise PublishError(
                    "Error validating access token: Session has expired",
                    code=190,
                    retryable=False,
                    auth_error=True,
                )
            return PublishResult(remote_id=f"ok-{self.platform}", progress={})

    class _Factory(PublisherFactory):
        def __init__(self) -> None:
            super().__init__(
                AppConfig(facebook_pages=[{"id": "p1", "name": "Page", "access_token": "dead"}])
            )

        def create(self, platform: str) -> Publisher:
            return _Publisher(platform)

    worker = PublicationWorker(db, _Factory())
    first = worker.run_once()
    second = worker.run_once()

    assert first.paused is True
    assert second.paused is True
    assert calls == ["facebook:p1", "telegram", "telegram"]
    assert "Пропущено без нового запиту" in second.failed_platforms["facebook:p1"]
    assert db.get_batch(first_id).status == "paused"
    assert db.get_batch(second_id).status == "paused"
    assert {target.platform: target.status for target in db.get_batch(second_id).targets}["telegram"] == "sent"

    worker.clear_auth_blocks("facebook")
    assert worker.auth_block_reason("facebook:p1") == ""


def test_fix23_bulk_reschedule_preserves_sent_targets_and_clears_failed_progress(tmp_path: Path) -> None:
    db = Database(tmp_path / "reschedule.sqlite3")
    first = _add_due_batch(db, "one", {"threads": "one", "telegram": "one"})
    second = _add_due_batch(db, "two", {"threads": "two"})
    for batch_id in (first, second):
        batch = db.get_batch(batch_id)
        with db.connect() as connection:
            connection.execute(
                "UPDATE publication_batches SET status='paused',attempts=9,lease_owner=NULL,lease_until=NULL WHERE id=?",
                (batch_id,),
            )
        for target in batch.targets:
            db.mark_target_failed(target.id, "expired token")
            db.save_target_progress(target.id, {"container_id": "stale"})
    first_batch = db.get_batch(first)
    telegram = next(target for target in first_batch.targets if target.platform == "telegram")
    db.mark_target_sent(telegram.id, "telegram-ok")

    start = datetime.now(UTC) + timedelta(hours=1)
    resumed = db.reschedule_paused_batches(
        {
            first: start.isoformat(),
            second: (start + timedelta(hours=1)).isoformat(),
        }
    )

    assert resumed == [first, second]
    one = db.get_batch(first)
    two = db.get_batch(second)
    assert one.status == two.status == "pending"
    assert one.attempts == two.attempts == 0
    one_targets = {target.platform: target for target in one.targets}
    assert one_targets["telegram"].status == "sent"
    assert one_targets["threads"].status == "pending"
    assert one_targets["threads"].last_error is None
    assert one_targets["threads"].progress == {}
    assert two.targets[0].status == "pending"


def test_fix23_recovery_also_reschedules_overdue_pending_without_replaying_sent(tmp_path: Path) -> None:
    db = Database(tmp_path / "overdue.sqlite3")
    batch_id = _add_due_batch(db, "overdue", {"facebook:p1": "fb", "telegram": "tg"})
    batch = db.get_batch(batch_id)
    telegram = next(target for target in batch.targets if target.platform == "telegram")
    db.mark_target_sent(telegram.id, "telegram-ok")

    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    resumed = db.reschedule_recoverable_batches({batch_id: future})

    assert resumed == [batch_id]
    recovered = db.get_batch(batch_id)
    assert recovered.status == "pending"
    targets = {target.platform: target.status for target in recovered.targets}
    assert targets == {"facebook:p1": "pending", "telegram": "sent"}


def test_fix23_facebook_and_threads_long_lived_exchange_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, float]] = []

    def fake_get(url: str, *, bearer: str = "", timeout: float = 12.0):
        calls.append((url, timeout))
        if "facebook.com" in url:
            return {"access_token": "fb-long", "expires_in": 5_184_000, "token_type": "bearer"}
        if "refresh_access_token" in url:
            return {"access_token": "th-refreshed", "expires_in": 5_184_000, "token_type": "bearer"}
        return {"access_token": "th-long", "expires_in": 5_184_000, "token_type": "bearer"}

    monkeypatch.setattr(setup, "_get_json", fake_get)
    facebook = setup.exchange_facebook_long_lived_token("short", "app", "secret", "v24.0")
    threads = setup.exchange_threads_long_lived_token("short", "secret")
    refreshed = setup.refresh_threads_long_lived_token("long")

    assert facebook.access_token == "fb-long"
    assert threads.access_token == "th-long"
    assert refreshed.access_token == "th-refreshed"
    assert all(timeout == 20 for _url, timeout in calls)
    assert "fb_exchange_token=short" in calls[0][0]
    assert "grant_type=th_exchange_token" in calls[1][0]
    assert "grant_type=th_refresh_token" in calls[2][0]


def test_fix23_ui_contract_is_non_modal_for_automatic_diagnostics_and_exposes_queue_recovery() -> None:
    source = (Path(__file__).parents[1] / "content_agent" / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert 'root.title("UA FREE Content Tool — v1.3.1-rc7")' in source
    assert 'text="Перепланувати пропущені / призупинені"' in source
    assert "def reschedule_interrupted_batches" in source
    assert "def _publication_result_from_worker" in source
    assert "Automatic diagnostics must never open a modal window" in source
    assert "should_warn = bool(action_items) and not automatic" in source
    assert 'self.queue_summary_var.set(' in source
    assert 'self.worker.clear_auth_blocks("facebook")' in source
    assert 'self.worker.clear_auth_blocks("threads")' in source
    assert 'self.settings_vars["facebook_app_secret"]' in source
    assert 'self.settings_vars["threads_app_secret"]' in source


def test_fix23_config_accepts_encrypted_meta_lifecycle_fields() -> None:
    config = AppConfig(
        meta_app_id="123",
        meta_app_secret="secret",
        meta_user_access_token="facebook",
        meta_user_token_expires_at="2026-09-01T10:00:00+03:00",
        threads_token="threads",
        threads_token_expires_at="2026-09-01T10:00:00+03:00",
        threads_token_refreshed_at="2026-07-29T10:00:00+03:00",
    )
    loaded = AppConfig.from_json_bytes(config.to_json_bytes())
    assert loaded.meta_app_secret == "secret"
    assert loaded.meta_user_token_expires_at.endswith("+03:00")
    assert loaded.threads_token_refreshed_at.endswith("+03:00")
