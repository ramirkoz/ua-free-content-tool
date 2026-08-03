from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from content_agent.config import AppConfig
from content_agent.database import Database
from content_agent.models import CollectedArticle
from content_agent.publishers import PublishContext, PublishResult, Publisher, PublisherFactory
from content_agent.scheduling import KYIV
from content_agent.ui.main_window import _format_kyiv_schedule, _format_overdue
from content_agent.worker import PublicationWorker

UTC = timezone.utc


def _db_with_article(tmp_path: Path, suffix: str = "one") -> tuple[Database, int]:
    db = Database(tmp_path / "fix13.sqlite3")
    source_id = db.add_source("rss", f"FIX13 {suffix}", f"https://example.com/{suffix}/feed")
    assert db.insert_collected(
        source_id,
        [
            CollectedArticle(
                f"fix13-{suffix}",
                f"FIX13 {suffix}",
                f"https://example.com/{suffix}",
                "Body",
                None,
            )
        ],
        enforce_today=False,
    ) == 1
    article = next(item for item in db.list_articles() if item.url.endswith(f"/{suffix}"))
    return db, article.id


def _add_article(db: Database, suffix: str) -> int:
    source_id = db.add_source("rss", f"FIX13 {suffix}", f"https://example.com/{suffix}/feed")
    assert db.insert_collected(
        source_id,
        [CollectedArticle(f"fix13-{suffix}", f"FIX13 {suffix}", f"https://example.com/{suffix}", "Body", None)],
        enforce_today=False,
    ) == 1
    return next(item.id for item in db.list_articles() if item.url.endswith(f"/{suffix}"))


def test_legacy_kyiv_offset_due_row_is_claimed_by_absolute_time(tmp_path: Path) -> None:
    db, article_id = _db_with_article(tmp_path)
    future = datetime.now(UTC) + timedelta(hours=1)
    queued = db.queue_targets(article_id, future.isoformat(), {"telegram": "payload"})
    legacy_past = (datetime.now(UTC) - timedelta(minutes=2)).astimezone(KYIV).isoformat(timespec="seconds")
    with db.connect() as connection:
        connection.execute(
            "UPDATE publication_batches SET scheduled_at=? WHERE id=?",
            (legacy_past, queued.batch_id),
        )
    claimed = db.claim_due_batch(owner="fix13-worker")
    assert claimed is not None
    assert claimed.id == queued.batch_id
    assert claimed.attempts == 1


def test_editing_overdue_pending_package_moves_same_batch_to_new_future_slot(tmp_path: Path) -> None:
    db, article_id = _db_with_article(tmp_path)
    original = db.queue_targets(
        article_id,
        (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        {"telegram": "tg"},
    )
    legacy_past = (datetime.now(UTC) - timedelta(hours=1)).astimezone(KYIV).isoformat(timespec="seconds")
    with db.connect() as connection:
        connection.execute(
            "UPDATE publication_batches SET scheduled_at=? WHERE id=?",
            (legacy_past, original.batch_id),
        )
    requested = datetime.now(UTC) + timedelta(minutes=20)
    changed = db.queue_targets(
        article_id,
        requested.astimezone(KYIV).isoformat(timespec="seconds"),
        {"telegram": "tg", "threads": "th"},
    )
    assert changed.batch_id == original.batch_id
    actual = datetime.fromisoformat(changed.scheduled_at)
    assert actual.tzinfo is not None
    assert abs((actual.astimezone(UTC) - requested).total_seconds()) < 2
    assert changed.scheduled_at.endswith("+00:00")


def test_latest_schedule_orders_mixed_offsets_by_instant_not_text(tmp_path: Path) -> None:
    db, first_article = _db_with_article(tmp_path, "first")
    second_article = _add_article(db, "second")
    first = db.queue_targets(
        first_article,
        datetime(2026, 7, 28, 8, 30, tzinfo=UTC).isoformat(),
        {"telegram": "first"},
    )
    second = db.queue_targets(
        second_article,
        datetime(2026, 7, 28, 8, 0, tzinfo=UTC).isoformat(),
        {"telegram": "second"},
    )
    # Lexically 10:00+03 looks later than 08:30+00, but by instant it is 07:00 UTC.
    with db.connect() as connection:
        connection.execute(
            "UPDATE publication_batches SET scheduled_at=? WHERE id=?",
            ("2026-07-28T10:00:00+03:00", second.batch_id),
        )
    latest = datetime.fromisoformat(db.latest_scheduled_at() or "")
    assert latest.astimezone(UTC) == datetime(2026, 7, 28, 8, 30, tzinfo=UTC)
    assert first.batch_id != second.batch_id


class _AlwaysPublisher(Publisher):
    def publish(self, text: str, progress: dict[str, object], context: PublishContext) -> PublishResult:
        context.before_write()
        return PublishResult(remote_id="ok", progress={})


class _AlwaysFactory(PublisherFactory):
    def __init__(self) -> None:
        super().__init__(AppConfig())

    def create(self, platform: str) -> Publisher:
        return _AlwaysPublisher()


def test_worker_wake_processes_new_due_package_without_waiting_full_poll(tmp_path: Path) -> None:
    db, article_id = _db_with_article(tmp_path)
    worker = PublicationWorker(db, _AlwaysFactory())
    stop = threading.Event()
    thread = threading.Thread(target=worker.run_loop, args=(stop, 60.0), daemon=True)
    thread.start()
    time.sleep(0.2)  # Let the first empty poll enter its long wait.
    queued = db.queue_targets(
        article_id,
        (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        {"telegram": "payload"},
    )
    worker.wake()
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and db.get_batch(queued.batch_id).status != "completed":
        time.sleep(0.05)
    stop.set()
    worker.wake()
    thread.join(timeout=2.0)
    assert db.get_batch(queued.batch_id).status == "completed"


def test_queue_time_is_displayed_in_kyiv_and_overdue_is_human_readable() -> None:
    text, local = _format_kyiv_schedule("2026-07-28T07:30:00+00:00")
    assert text == "28.07.2026 10:30"
    assert local is not None and local.utcoffset() == timedelta(hours=3)
    assert _format_overdue(timedelta(hours=1, minutes=24)) == "1 год 24 хв"


def test_fix13_ui_contract_has_periodic_queue_refresh_and_worker_wake() -> None:
    source = (Path(__file__).parents[1] / "content_agent" / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert 'root.title("UA FREE Content Tool — R8 FIX30")' in source
    assert "self._schedule_queue_refresh()" in source
    assert "self.worker.wake()" in source
    assert 'status_text = f"прострочено на' in source
    assert 'schedule_text + " (Київ)"' in source
