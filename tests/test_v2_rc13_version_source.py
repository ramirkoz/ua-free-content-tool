from pathlib import Path

from content_agent.version import APP_VERSION
from content_agent.v2.ui.window_rc11 import MainWindow


def test_rc13_runtime_version_matches_version_file() -> None:
    expected = Path("VERSION.txt").read_text(encoding="utf-8").strip()
    assert APP_VERSION == expected == "2.0.0-rc13"
    assert MainWindow.VERSION_LABEL == expected


def test_active_ui_has_no_hardcoded_rc11_version_label() -> None:
    main_source = Path("content_agent/main.py").read_text(encoding="utf-8")
    window_source = Path("content_agent/v2/ui/window_rc11.py").read_text(encoding="utf-8")
    assert 'v2.0.0-rc11' not in main_source
    assert 'v2.0.0-rc11' not in window_source
    assert "APP_VERSION" in main_source
    assert "APP_VERSION" in window_source
