from __future__ import annotations

from types import SimpleNamespace

from content_agent.config import AppConfig
from content_agent.network import HttpResponse
from content_agent.trends import check_threads_keyword_access
from content_agent.ui import main_window
from content_agent.ui.main_window import MainWindow


class FakeVar:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


def test_threads_permission_uses_current_official_endpoint_and_short_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch(url: str, **kwargs) -> HttpResponse:
        captured["url"] = url
        captured.update(kwargs)
        return HttpResponse(200, {"content-type": "application/json"}, b'{"data":[]}', url)

    monkeypatch.setattr("content_agent.trends.fetch_url", fake_fetch)
    assert check_threads_keyword_access("token")[0] is True
    assert str(captured["url"]).startswith("https://graph.threads.net/keyword_search?")
    assert "/v1.0/keyword_search" not in str(captured["url"])
    assert captured["timeout"] == 12


def test_threads_ui_check_finishes_visibly_and_saves_working_token(monkeypatch) -> None:
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(main_window, "check_threads_keyword_access", lambda token: (True, "ok"))
    monkeypatch.setattr(
        main_window.messagebox,
        "showinfo",
        lambda title, text, parent=None: messages.append((title, text)),
    )

    window = MainWindow.__new__(MainWindow)
    window.root = object()
    window.settings_vars = {"threads_token": FakeVar("new-token")}
    window.threads_search_status_var = FakeVar()
    window.config = AppConfig(threads_token="old-token")
    persisted: list[str] = []
    window._persist_connected_config = lambda message: persisted.append(message)

    def run_now(action, success, **_kwargs) -> None:
        success(action())

    window.run_async = run_now
    window.check_threads_trends()

    assert window.config.threads_token == "new-token"
    assert "ПІДКЛЮЧЕНО" in window.threads_search_status_var.get()
    assert persisted
    assert messages and "threads_keyword_search" in messages[0][1]


def test_threads_ui_check_does_not_repeat_profile_request() -> None:
    source = __import__("inspect").getsource(MainWindow.check_threads_trends)
    assert "inspect_threads_token" not in source
    assert "до 12 секунд" in source
    assert "showwarning" in source and "showinfo" in source
