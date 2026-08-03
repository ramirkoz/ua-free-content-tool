from __future__ import annotations

from types import SimpleNamespace

from content_agent.ui import main_window
from content_agent.ui.main_window import MainWindow


class FakeVar:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class FakeProgress:
    def __init__(self) -> None:
        self.running = False

    def start(self, _interval: int) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False


class FakeButton:
    def __init__(self) -> None:
        self.state = "normal"

    def configure(self, *, state: str) -> None:
        self.state = state


class ScheduledRoot:
    def __init__(self) -> None:
        self.callbacks: dict[str, object] = {}
        self.counter = 0

    def after(self, delay: int, callback):
        self.counter += 1
        key = f"after-{self.counter}"
        self.callbacks[key] = (delay, callback)
        return key

    def after_cancel(self, key: str) -> None:
        self.callbacks.pop(key, None)

    def fire_delay(self, delay: int) -> None:
        for key, value in list(self.callbacks.items()):
            stored_delay, callback = value
            if stored_delay == delay:
                self.callbacks.pop(key, None)
                callback()
                return
        raise AssertionError(f"no callback for delay {delay}")


def _window() -> MainWindow:
    window = MainWindow.__new__(MainWindow)
    window.root = ScheduledRoot()
    window.operation_var = FakeVar("Поточна операція: немає")
    window.operation_detail_var = FakeVar("Готово")
    window.status_var = FakeVar("Готово")
    window.operation_running = False
    window.operation_started_at = None
    window.operation_tick_after_id = None
    window.operation_timeout_after_id = None
    window.operation_serial = 0
    window.active_operation_id = None
    window.operation_progress = FakeProgress()
    window.operation_buttons = [FakeButton()]
    window.set_status = lambda value: window.status_var.set(value)
    window._operation_tick = lambda: None
    return window


def test_hard_timeout_finishes_ui_and_shows_error(monkeypatch) -> None:
    shown: list[str] = []
    monkeypatch.setattr(
        main_window.messagebox,
        "showerror",
        lambda _title, text, parent=None: shown.append(text),
    )
    window = _window()
    timeout_status = FakeVar()

    operation_id = window._start_operation("Threads")
    assert operation_id == 1
    window.operation_timeout_after_id = window.root.after(
        12000,
        lambda: window._operation_timeout(
            operation_id,
            "Threads не відповів за 12 секунд.",
            lambda message: timeout_status.set(message),
        ),
    )

    window.root.fire_delay(12000)

    assert not window.operation_running
    assert window.active_operation_id is None
    assert not window.operation_progress.running
    assert window.operation_buttons[0].state == "normal"
    assert "12 секунд" in window.operation_detail_var.get()
    assert "12 секунд" in timeout_status.get()
    assert shown == ["Threads не відповів за 12 секунд."]


def test_late_result_after_timeout_is_ignored(monkeypatch) -> None:
    shown: list[str] = []
    monkeypatch.setattr(main_window.messagebox, "showerror", lambda *args, **kwargs: None)
    window = _window()
    success_calls: list[object] = []

    operation_id = window._start_operation("Threads")
    assert operation_id == 1
    window._operation_timeout(operation_id, "timeout", None)
    window._async_success_for_operation(
        operation_id,
        SimpleNamespace(id="42"),
        lambda value: success_calls.append(value),
        "done",
    )

    assert success_calls == []
    assert window.operation_var.get() == "Поточна операція: помилка"


def test_threads_buttons_request_real_ui_timeout() -> None:
    source = MainWindow.connect_threads.__code__.co_consts
    assert 12 in source
    keyword_source = MainWindow.check_threads_trends.__code__.co_consts
    assert 12 in keyword_source
