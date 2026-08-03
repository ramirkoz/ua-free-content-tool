from __future__ import annotations

import inspect
from types import SimpleNamespace

from content_agent.config import AppConfig
from content_agent.ui.main_window import AUTO_COLLECT_INTERVAL_MS, MainWindow


def test_sources_ui_has_no_manual_collection_buttons() -> None:
    source = inspect.getsource(MainWindow._build_sources_tab)
    assert "Зібрати всі" not in source
    assert "Зібрати вибране" not in source
    assert "Автоматичне оновлення" in source


def test_auto_collection_cannot_be_disabled_by_legacy_config() -> None:
    calls: list[int] = []
    labels: list[str] = []

    class FakeRoot:
        def after(self, delay: int, callback):
            calls.append(delay)
            return "after-fix2"

        def after_cancel(self, identifier: str) -> None:
            raise AssertionError(identifier)

    window = MainWindow.__new__(MainWindow)
    window.root = FakeRoot()
    window.config = AppConfig(auto_collect_on_start=False)
    window.stop_event = SimpleNamespace(is_set=lambda: False)
    window.auto_collect_after_id = None
    window.auto_collect_status_var = SimpleNamespace(set=labels.append)
    window._schedule_next_auto_collect()

    assert calls == [AUTO_COLLECT_INTERVAL_MS]
    assert window.auto_collect_after_id == "after-fix2"
    assert labels and "наступна перевірка" in labels[-1]


def test_settings_do_not_offer_manual_auto_collection_toggle() -> None:
    source = inspect.getsource(MainWindow._build_settings_tab)
    assert "auto_collect_var" not in source
    assert "перевіряються автоматично" in source
