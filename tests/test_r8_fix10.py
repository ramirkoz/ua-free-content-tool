from __future__ import annotations

from types import SimpleNamespace

from content_agent.config import AppConfig
from content_agent.ui import main_window
from content_agent.ui.main_window import MainWindow


class FakeVar:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class ImmediateRoot:
    def after(self, _delay: int, callback):
        callback()


def test_profile_button_finishes_visibly_without_auto_keyword_check(monkeypatch) -> None:
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main_window,
        "inspect_threads_token",
        lambda token: SimpleNamespace(id="42", username="uafree", name="UA FREE"),
    )
    monkeypatch.setattr(
        main_window.messagebox,
        "showinfo",
        lambda title, text, parent=None: messages.append((title, text)),
    )

    window = MainWindow.__new__(MainWindow)
    window.root = ImmediateRoot()
    window.settings_vars = {"threads_token": FakeVar("new-token")}
    window.threads_status_var = FakeVar()
    window.config = AppConfig(threads_token="old-token")
    persisted: list[str] = []
    window._persist_connected_config = lambda message: persisted.append(message)
    window.check_threads_trends = lambda: (_ for _ in ()).throw(AssertionError("unexpected auto keyword check"))

    def run_now(action, success, **kwargs) -> None:
        assert "до 12 секунд" in kwargs["label"]
        success(action())

    window.run_async = run_now
    window.connect_threads()

    assert window.config.threads_token == "new-token"
    assert window.config.threads_user_id == "42"
    assert "@uafree" in window.threads_status_var.get()
    assert persisted
    assert messages and "Пошук трендів перевіряється окремою кнопкою" in messages[0][1]


def test_profile_button_error_updates_threads_status(monkeypatch) -> None:
    monkeypatch.setattr(
        main_window,
        "inspect_threads_token",
        lambda token: (_ for _ in ()).throw(RuntimeError("test failure")),
    )
    window = MainWindow.__new__(MainWindow)
    window.root = ImmediateRoot()
    window.settings_vars = {"threads_token": FakeVar("bad-token")}
    window.threads_status_var = FakeVar()
    window.config = AppConfig()

    def run_now(action, success, **kwargs) -> None:
        try:
            action()
        except RuntimeError:
            pass

    window.run_async = run_now
    window.connect_threads()
    assert "НЕ ПІДКЛЮЧЕНО" in window.threads_status_var.get()
    assert "test failure" in window.threads_status_var.get()
