from __future__ import annotations

import inspect
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from content_agent.v2.ai.contracts import AIRequest
from content_agent.v2.ai import service as ai_service
from content_agent.v2.publishing.outcomes import PublicationOutcome
from content_agent.v2.storage.factory import create_database
from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow as ActiveMainWindow
from content_agent.v2.ui.manual_topics_window import MainWindow as Rc43MainWindow
from content_agent.ui import v1_4_rc15_window as rc15


def _seed_target(db, platform: str = "linkedin") -> tuple[int, int, int]:
    source_id = db.add_source("rss", "RC48 source", "https://example.com/rc48-feed")
    now = datetime.now(timezone.utc).isoformat()
    with db.connect() as con:
        group_id = int(
            con.execute(
                "INSERT INTO news_groups(canonical_title,created_at,updated_at) VALUES(?,?,?)",
                ("RC48", now, now),
            ).lastrowid
        )
        article_id = int(
            con.execute(
                "INSERT INTO articles(source_id,group_id,external_id,content_hash,title,url,raw_text,discovered_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (source_id, group_id, "rc48", "rc48-hash", "RC48", "https://example.com/a", "body", now),
            ).lastrowid
        )
    batch_id = db.create_batch(
        article_id,
        (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        {platform: "hello"},
    )
    target_id = db.get_batch(batch_id).targets[0].id
    return group_id, batch_id, target_id


def test_rc15_filter_has_private_state_and_v2_optout() -> None:
    source = inspect.getsource(rc15.MainWindow)
    assert "_rc15_source_filter_var" in source
    assert "_disable_rc15_source_filter" in source
    assert "self.inbox_source_filter_var =" not in source


def test_unknown_target_operator_can_confirm_post_exists(tmp_path: Path) -> None:
    db = create_database(tmp_path / "sent.sqlite3")
    _group_id, _batch_id, target_id = _seed_target(db)
    db.mark_target_failed(target_id, "Результат невідомий; перевірте платформу вручну")
    assert db.publication_target_outcome(target_id) is PublicationOutcome.UNKNOWN

    db.confirm_target_sent(target_id)

    assert db.publication_target_outcome(target_id) is PublicationOutcome.SENT
    with db.connect() as con:
        row = con.execute(
            "SELECT status,last_error,progress_json FROM publication_targets WHERE id=?",
            (target_id,),
        ).fetchone()
    assert row["status"] == "sent"
    assert row["last_error"] is None
    assert "operator_confirmed_sent_at" in str(row["progress_json"])


def test_unknown_target_operator_can_confirm_no_post_and_resume(tmp_path: Path) -> None:
    db = create_database(tmp_path / "not-sent.sqlite3")
    _group_id, batch_id, target_id = _seed_target(db)
    db.mark_target_failed(target_id, "unknown outcome; перевірте платформу вручну")
    db.confirm_target_not_sent(target_id)
    assert db.publication_target_outcome(target_id) is PublicationOutcome.CONFIRMED_NOT_SENT
    db.resume_batch(batch_id)
    assert db.get_batch(batch_id).status == "pending"


def test_rc48_group_helper_reads_explicit_unknown_outcome(tmp_path: Path) -> None:
    db = create_database(tmp_path / "history.sqlite3")
    group_id, _batch_id, target_id = _seed_target(db)
    db.mark_target_failed(target_id, "Результат невідомий; перевірте платформу вручну")

    window = object.__new__(ActiveMainWindow)
    window.db = db
    unknown = ActiveMainWindow._rc48_unknown_targets(window, group_id)

    assert len(unknown) == 1
    assert int(unknown[0]["id"]) == target_id
    assert unknown[0]["outcome"] == PublicationOutcome.UNKNOWN.value


def test_rewrite_does_not_erase_manual_text_without_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    asked: list[tuple[str, str]] = []

    monkeypatch.setattr(Rc43MainWindow, "rewrite_current", lambda self: called.append(True))

    class FakeText:
        def get(self, _start, _end):
            return "Ручна редактура"

    class FakeDb:
        def get_group(self, _group_id):
            return SimpleNamespace(ai_draft_text="Попередня AI-чернетка")

    class FakeMsg:
        def askyesno(self, title, text, **_kwargs):
            asked.append((title, text))
            return False

    window = object.__new__(ActiveMainWindow)
    window.current_group_id = 7
    window.text_widgets = {"rewrite": FakeText()}
    window.db = FakeDb()
    window.msg = FakeMsg()
    window.root = object()

    ActiveMainWindow.rewrite_current(window)

    assert asked
    assert called == []


def test_rewrite_continues_after_explicit_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    monkeypatch.setattr(Rc43MainWindow, "rewrite_current", lambda self: called.append(True))

    class FakeText:
        def get(self, _start, _end):
            return "Ручна редактура"

    class FakeDb:
        def get_group(self, _group_id):
            return SimpleNamespace(ai_draft_text="Попередня AI-чернетка")

    class FakeMsg:
        def askyesno(self, *_args, **_kwargs):
            return True

    window = object.__new__(ActiveMainWindow)
    window.current_group_id = 7
    window.text_widgets = {"rewrite": FakeText()}
    window.db = FakeDb()
    window.msg = FakeMsg()
    window.root = object()

    ActiveMainWindow.rewrite_current(window)
    assert called == [True]


def test_legacy_router_execution_is_serialized(monkeypatch: pytest.MonkeyPatch) -> None:
    from content_agent import ai_router
    from content_agent.v2.ai.settings import AIBackendSettings, BACKEND_ROUTER

    active = 0
    max_active = 0
    guard = threading.Lock()
    start = threading.Barrier(3)

    def fake_run(*_args, **_kwargs):
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.08)
        with guard:
            active -= 1
        return SimpleNamespace(text="ok", provider="fake", model="m", label="fake", attempted=())

    monkeypatch.setattr(ai_router, "run_ai_router", fake_run)
    monkeypatch.setattr(ai_service, "load_backend_settings", lambda: AIBackendSettings(active_backend=BACKEND_ROUTER))
    request = AIRequest(prompt="test")
    errors: list[BaseException] = []

    def runner():
        try:
            start.wait(timeout=2)
            ai_service.execute_request(request)
        except BaseException as exc:  # pragma: no cover - assertion below reports it
            errors.append(exc)

    first = threading.Thread(target=runner)
    second = threading.Thread(target=runner)
    first.start(); second.start()
    start.wait(timeout=2)
    first.join(timeout=3); second.join(timeout=3)

    assert errors == []
    assert max_active == 1


def test_rc48_adds_no_new_versioned_mainwindow_layer() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    forbidden = [
        path.relative_to(repo_root).as_posix()
        for path in (repo_root / "content_agent").rglob("*.py")
        if "window_rc48" in path.name.casefold()
    ]
    assert forbidden == []
