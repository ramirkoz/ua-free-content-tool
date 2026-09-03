from __future__ import annotations

from datetime import datetime

from content_agent.database_v1_4_rc9 import Database
from content_agent.destinations_v1_4 import DestinationSchedule
from content_agent.models import PublicationBatch, PublicationTarget
from content_agent.scheduling import KYIV, parse_iso
from content_agent.source_management_v1_4_rc9 import detect_source_kind, resolve_source_kind
from content_agent.ui.v1_4_rc9_window import MainWindow


def test_source_type_detection_and_strong_signal_correction() -> None:
    assert detect_source_kind("@ctrlua") == "telegram"
    assert detect_source_kind("https://t.me/ctrlua") == "telegram"
    assert detect_source_kind("https://example.com/feed/") == "rss"
    assert detect_source_kind("https://example.com/news.xml") == "rss"
    assert detect_source_kind("https://example.com/article/42") == "url"

    # Obvious mistakes are corrected automatically.
    assert resolve_source_kind("https://t.me/ctrlua", "url") == "telegram"
    assert resolve_source_kind("https://example.com/rss", "url") == "rss"
    # An unusual feed with a generic URL can still be forced manually.
    assert resolve_source_kind("https://example.com/stream", "rss") == "rss"


def test_database_can_edit_and_bulk_delete_sources(tmp_path) -> None:
    db = Database(tmp_path / "content.sqlite3")
    first = db.add_source("url", "Wrong Telegram", "https://t.me/example")
    second = db.add_source("url", "Web", "https://example.com/a")
    third = db.add_source("rss", "Feed", "https://example.com/feed")

    db.update_source(first, kind="telegram", name="Telegram", url="https://t.me/example")
    edited = next(item for item in db.list_sources() if item.id == first)
    assert edited.kind == "telegram"
    assert edited.name == "Telegram"
    assert edited.last_checked_at is None

    deleted = db.delete_sources([first, third])
    assert deleted == 2
    assert [item.id for item in db.list_sources()] == [second]


class _Messages:
    def askyesno(self, *_args, **_kwargs) -> bool:
        return True

    def showinfo(self, *_args, **_kwargs) -> None:
        return None

    def showwarning(self, *_args, **_kwargs) -> None:
        return None


class _Store:
    def __init__(self) -> None:
        self.rules = {
            "telegram": DestinationSchedule(0, 1, 15),
            "threads": DestinationSchedule(12, 13, 15),
        }

    def get(self, key: str) -> DestinationSchedule:
        return self.rules[key]


class _Worker:
    def wake(self) -> None:
        return None


def _batch(batch_id: int, platform: str) -> PublicationBatch:
    return PublicationBatch(
        id=batch_id,
        article_id=batch_id,
        scheduled_at=datetime.now(KYIV).isoformat(timespec="seconds"),
        status="paused",
        lease_owner=None,
        lease_until=None,
        attempts=1,
        targets=[
            PublicationTarget(
                id=batch_id,
                batch_id=batch_id,
                platform=platform,
                status="pending",
            )
        ],
    )


class _ScheduleDb:
    def __init__(self) -> None:
        self.recoverable = [_batch(1, "telegram"), _batch(2, "threads")]
        self.saved: dict[int, str] = {}

    def list_batches(self, *, limit: int, statuses: set[str]):
        if statuses == {"paused", "pending"}:
            return list(self.recoverable)
        if statuses == {"pending", "in_progress"}:
            return []
        raise AssertionError(statuses)

    def reschedule_recoverable_batches(self, schedules: dict[int, str]) -> int:
        self.saved = dict(schedules)
        return len(schedules)


def test_recovery_uses_each_destination_schedule_not_global_config() -> None:
    window = object.__new__(MainWindow)
    window.db = _ScheduleDb()
    window._destination_schedule_store = _Store()
    window.msg = _Messages()
    window.root = object()
    window.worker = _Worker()
    window.refresh_queue = lambda: None
    window.set_status = lambda _text: None

    window.reschedule_interrupted_batches()

    telegram = parse_iso(window.db.saved[1])
    threads = parse_iso(window.db.saved[2])
    assert telegram is not None and threads is not None
    assert telegram.astimezone(KYIV).hour == 0
    assert threads.astimezone(KYIV).hour == 12
