from __future__ import annotations

import threading

from content_agent.v2.storage.factory import create_database
from content_agent.v2.supervisor import runtime as supervisor_runtime


class _FakeRoot:
    def __init__(self) -> None:
        self.idle_callbacks = []

    def after_idle(self, callback):
        self.idle_callbacks.append(callback)
        return "idle-1"


class _FakeWindow:
    def __init__(self) -> None:
        self.root = _FakeRoot()
        self.stop_event = threading.Event()
        self._ui_ready = False


class _Settings:
    supervisor_enabled = True


class _FakeThread:
    def __init__(self, *, target, name, daemon) -> None:
        self.target = target
        self.name = name
        self.daemon = daemon
        self.started = False

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return self.started


def test_supervisor_waits_for_complete_ui(monkeypatch) -> None:
    window = _FakeWindow()
    monkeypatch.setattr(supervisor_runtime, "load_backend_settings", lambda: _Settings())
    monkeypatch.setattr(supervisor_runtime, "mark_startup_healthy", lambda _version: None)
    monkeypatch.setattr(supervisor_runtime.threading, "Thread", _FakeThread)

    runtime = supervisor_runtime.SupervisorRuntime(window, object(), object(), version="2.0.0-rc49")
    monkeypatch.setattr(runtime, "_install_exception_hooks", lambda: None)

    runtime.start()
    assert runtime.thread is None
    assert len(window.root.idle_callbacks) == 1

    window._ui_ready = True
    window.root.idle_callbacks.pop()()
    assert runtime.thread is not None
    assert runtime.thread.is_alive()


def test_articles_discovered_at_migration_is_indexed(tmp_path) -> None:
    database = create_database(tmp_path / "content_agent.sqlite3")
    with database.connect() as db:
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_articles_discovered_at'"
        ).fetchone()
        assert row is not None
        plan = db.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT published_at, discovered_at FROM articles "
            "WHERE discovered_at >= ? AND discovered_at < ?",
            ("2026-09-29T00:00:00+00:00", "2026-09-30T00:00:00+00:00"),
        ).fetchall()
    text = " ".join(str(item) for row in plan for item in row)
    assert "idx_articles_discovered_at" in text


def test_today_counter_no_longer_wraps_indexed_column_in_julianday() -> None:
    from inspect import getsource
    from content_agent.database_v1_4_rc21 import Database

    source = getsource(Database.count_today_articles)
    assert "julianday(discovered_at)" not in source
    assert "discovered_at >= ?" in source
    assert "discovered_at < ?" in source
