from __future__ import annotations


def test_rc49_stable_window_exposes_ai_provider_callbacks() -> None:
    from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow

    assert callable(getattr(MainWindow, "save_ai_provider_keys", None))
    assert callable(getattr(MainWindow, "test_ai_router_ui", None))


def test_rc49_main_keeps_stable_rc44_shell() -> None:
    from content_agent import main
    from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow

    assert main.MainWindow is MainWindow
