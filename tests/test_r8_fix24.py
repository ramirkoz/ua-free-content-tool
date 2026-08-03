from __future__ import annotations

from types import SimpleNamespace

import content_agent.ui.main_window as mw
from content_agent.config import AppConfig
from content_agent.connection_diagnostics import (
    ConnectionDiagnostic,
    ConnectionDiagnosticsReport,
    STATUS_ATTENTION,
    STATUS_REPLACE,
)
from content_agent.ui.main_window import MainWindow


class _Var:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class _Root:
    def after(self, _delay: int, _callback):
        return "after"


def test_fix25_threads_profile_uses_real_12_second_ui_timeout() -> None:
    window = MainWindow.__new__(MainWindow)
    window.root = _Root()
    window.config = AppConfig()
    window.settings_vars = {
        "threads_token": _Var("token"),
        "meta_app_secret": _Var(""),
    }
    window.threads_status_var = _Var()
    captured: dict[str, object] = {}

    def fake_run_async(action, success, **kwargs):
        captured.update(kwargs)
        captured["action"] = action
        captured["success"] = success

    window.run_async = fake_run_async  # type: ignore[method-assign]
    window.connect_threads()

    assert captured["timeout_seconds"] == 12
    assert callable(captured["on_timeout"])
    assert "12 секунд" in str(captured["timeout_message"])


def test_fix25_automatic_diagnostics_are_non_modal_but_manual_check_warns(monkeypatch) -> None:
    window = MainWindow.__new__(MainWindow)
    window.root = SimpleNamespace()
    window.config = AppConfig()
    window.connection_diagnostics_running = True
    window.last_connection_warning_signature = ()
    window.set_status = lambda _value: None
    window._persist_diagnostic_metadata = lambda *_args: None
    window._schedule_connection_diagnostics = lambda: None
    window.queue_alert_var = _Var()
    window.connection_diagnostics_status_var = _Var()

    class _Tree:
        def __init__(self) -> None:
            self.rows: dict[str, tuple[object, ...]] = {}

        def delete(self, *_items) -> None:
            self.rows.clear()

        def get_children(self):
            return tuple(self.rows)

        def insert(self, _parent, _where, *, iid, values) -> None:
            self.rows[str(iid)] = tuple(values)

    window.connection_diagnostics_tree = _Tree()
    seen: list[str] = []
    monkeypatch.setattr(mw.messagebox, "showwarning", lambda _title, message, parent=None: seen.append(message))
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *_args, **_kwargs: None)

    report = ConnectionDiagnosticsReport(
        items=(
            ConnectionDiagnostic("facebook", "Facebook", STATUS_REPLACE, "Токен треба замінити"),
            ConnectionDiagnostic("telegram", "Telegram", STATUS_ATTENTION, "Додайте бота адміністратором"),
        )
    )

    window._connection_diagnostics_completed(report, AppConfig(), True)
    assert len(window.connection_diagnostics_tree.get_children()) == 2
    assert "Потрібна увага" in window.connection_diagnostics_status_var.get()
    assert seen == []

    window._connection_diagnostics_completed(report, AppConfig(), False)
    assert len(seen) == 1
    assert "Facebook" in seen[0] and "Telegram" in seen[0]
