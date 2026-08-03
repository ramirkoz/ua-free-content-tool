from __future__ import annotations

from types import SimpleNamespace

from content_agent.config import AppConfig
from content_agent.network import HttpResponse
from content_agent.trends import check_threads_keyword_access
from content_agent.ui import main_window
from content_agent.ui.main_window import AUTO_COLLECT_INTERVAL_MS, MainWindow, target_labels


def test_target_labels_identify_networks() -> None:
    config = AppConfig(
        telegram_chat_id="@uafree_org",
        facebook_page_1_name="Волонтерська банда",
        facebook_page_2_name="Ініціатива",
        threads_profile_name="Антон Козирєв",
        linkedin_profile_name="Антон Козирєв",
    )
    labels = target_labels(config)
    assert labels["threads"] == "Антон Козирєв (Threads)"
    assert labels["linkedin"] == "Антон Козирєв (LinkedIn)"
    assert labels["facebook:1"].endswith("(Facebook)")
    assert labels["telegram"].endswith("(Telegram)")


def test_threads_keyword_permission_probe_success(monkeypatch) -> None:
    monkeypatch.setattr(
        "content_agent.trends.fetch_url",
        lambda *args, **kwargs: HttpResponse(200, {"content-type": "application/json"}, b'{"data": []}', "https://graph.threads.net/keyword_search"),
    )
    assert check_threads_keyword_access("token") == (True, "Дозвіл threads_keyword_search працює.")


def test_threads_keyword_permission_probe_reports_meta_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "content_agent.trends.fetch_url",
        lambda *args, **kwargs: HttpResponse(403, {"content-type": "application/json"}, b'{"error":{"message":"Missing threads_keyword_search"}}', "https://graph.threads.net/keyword_search"),
    )
    available, detail = check_threads_keyword_access("token")
    assert available is False
    assert "threads_keyword_search" in detail


def test_auto_collection_reschedules_for_five_minutes() -> None:
    calls: list[tuple[int, object]] = []

    class FakeRoot:
        def after(self, delay: int, callback):
            calls.append((delay, callback))
            return "after-1"

        def after_cancel(self, identifier: str) -> None:
            raise AssertionError(identifier)

    window = MainWindow.__new__(MainWindow)
    window.root = FakeRoot()
    window.config = AppConfig(auto_collect_on_start=False)
    window.stop_event = SimpleNamespace(is_set=lambda: False)
    window.auto_collect_after_id = None
    window.auto_collect_status_var = SimpleNamespace(set=lambda value: None)
    window._schedule_next_auto_collect()
    assert calls and calls[0][0] == AUTO_COLLECT_INTERVAL_MS
    assert window.auto_collect_after_id == "after-1"
