from __future__ import annotations

import inspect
from types import SimpleNamespace

from content_agent.config import AppConfig
from content_agent.platform_setup import MetaPage, ThreadsProfile, load_meta_pages
from content_agent.publishers import FacebookPagePublisher, PublisherFactory
from content_agent.ui import main_window
from content_agent.ui.main_window import MainWindow, publication_target_keys, target_labels


class DummyVar:
    def __init__(self, value: str = ""):
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


def test_all_facebook_pages_become_publication_targets() -> None:
    pages = [
        {"id": str(index), "name": f"Page {index}", "access_token": f"token-{index}"}
        for index in range(10, 15)
    ]
    config = AppConfig(facebook_pages=pages)
    config.sync_legacy_facebook_slots()

    keys = publication_target_keys(config)
    facebook_keys = [key for key in keys if key.startswith("facebook:")]
    assert facebook_keys == [f"facebook:{index}" for index in range(10, 15)]
    assert all(config.platform_ready(key) for key in facebook_keys)
    labels = target_labels(config)
    assert labels["facebook:14"] == "Page 14 (Facebook)"


def test_publisher_factory_supports_any_configured_facebook_page() -> None:
    config = AppConfig(
        facebook_pages=[
            {"id": "100", "name": "First", "access_token": "one"},
            {"id": "200", "name": "Second", "access_token": "two"},
            {"id": "300", "name": "Third", "access_token": "three"},
        ]
    )
    config.sync_legacy_facebook_slots()
    publisher = PublisherFactory(config).create("facebook:300")
    assert isinstance(publisher, FacebookPagePublisher)
    assert publisher.page_id == "300"
    assert publisher.token == "three"


def test_old_two_page_config_is_migrated_to_page_list() -> None:
    config = AppConfig.from_json_bytes(
        b'{"facebook_page_1_id":"11","facebook_page_1_name":"One","facebook_page_1_token":"t1",'
        b'"facebook_page_2_id":"22","facebook_page_2_name":"Two","facebook_page_2_token":"t2"}'
    )
    assert [row["id"] for row in config.facebook_pages] == ["11", "22"]
    assert config.platform_ready("facebook:11")
    assert config.platform_ready("facebook:22")


def test_meta_page_loader_reads_all_pagination_pages(monkeypatch) -> None:
    calls: list[str] = []

    def fake_get(url: str, *, bearer: str = "") -> dict[str, object]:
        calls.append(url)
        assert bearer == "user-token"
        if len(calls) == 1:
            return {
                "data": [{"id": "1", "name": "One", "access_token": "t1"}],
                "paging": {"next": "https://graph.facebook.com/v24.0/me/accounts?after=abc"},
            }
        return {"data": [{"id": "2", "name": "Two", "access_token": "t2"}]}

    monkeypatch.setattr("content_agent.platform_setup._get_json", fake_get)
    pages = load_meta_pages("user-token", "v24.0")
    assert pages == [MetaPage("1", "One", "t1"), MetaPage("2", "Two", "t2")]
    assert len(calls) == 2


def test_font_size_is_persisted_config_and_validated() -> None:
    config = AppConfig(ui_font_size=18)
    config.validate()
    loaded = AppConfig.from_json_bytes(b'{}')
    assert loaded.ui_font_size == 12


def test_settings_have_sticky_save_and_unsaved_close_guard() -> None:
    settings_source = inspect.getsource(MainWindow._build_settings_tab)
    close_source = inspect.getsource(MainWindow.close)
    assert "ЗБЕРЕГТИ ЗМІНИ" in settings_source
    assert "settings_save_button" in settings_source
    assert "Незбережені налаштування" in close_source
    assert "save_settings" in close_source


def test_threads_keyword_check_persists_new_token(monkeypatch) -> None:
    window = MainWindow.__new__(MainWindow)
    window.settings_vars = {"threads_token": DummyVar("new-token")}
    window.threads_search_status_var = DummyVar()
    window.threads_status_var = DummyVar()
    window.config = AppConfig(threads_token="old-token", threads_user_id="old", threads_profile_name="Old")
    saved: list[str] = []
    window._persist_connected_config = saved.append  # type: ignore[method-assign]

    def run_async(action, success=None, **_kwargs):
        result = action()
        if success:
            success(result)

    window.run_async = run_async  # type: ignore[method-assign]
    monkeypatch.setattr(main_window, "check_threads_keyword_access", lambda token: (True, "ok"))
    monkeypatch.setattr(main_window.messagebox, "showinfo", lambda *args, **kwargs: None)

    window.check_threads_trends()

    assert window.config.threads_token == "new-token"
    assert window.config.threads_user_id == "old"
    assert saved == ["Threads keyword search підключено; токен збережено"]
    assert "ПІДКЛЮЧЕНО" in window.threads_search_status_var.get()
