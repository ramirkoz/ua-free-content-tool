from __future__ import annotations

import os
import tkinter as tk

import pytest

from content_agent.app.container import build_services
from content_agent.config import AppConfig
from content_agent.paths import reset_path_cache_for_tests
from content_agent.v2.storage.factory import create_database
from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow


@pytest.mark.skipif(os.name != "nt", reason="RC50 final UI acceptance runs on Windows")
def test_real_main_window_builds_all_tabs_and_ai_refreshes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UA_FREE_CONTENT_DATA", str(tmp_path / "Data"))
    monkeypatch.setenv("UA_FREE_TEST_PLAINTEXT_CONFIG", "1")
    reset_path_cache_for_tests()
    db = create_database(tmp_path / "Data" / "content_agent.sqlite3")
    services = build_services(config=AppConfig(), database=db)

    root = tk.Tk()
    root.withdraw()
    window = None
    try:
        window = MainWindow(root, services)
        window._ui_ready = True
        window.refresh_v2_ai_status()
        root.deiconify()
        root.update_idletasks()

        labels = [window.notebook.tab(tab_id, "text") for tab_id in window.notebook.tabs()]
        assert "AI" in labels
        assert "Платформи" in labels
        assert "Дані й резервні копії" in labels
        assert "Стан системи" in labels
        assert hasattr(window, "_rc48_status_bar")
        assert hasattr(window, "v2_platforms_tree")

        # RC50 layout acceptance matrix derived from the UI audit. We validate the
        # mapped active shell at the logical sizes that correspond to 100/125/150/175%.
        for width, height in ((1440, 920), (1536, 824), (1280, 680), (1097, 577)):
            root.geometry(f"{width}x{height}")
            root.update_idletasks()
            assert window.notebook.winfo_width() > 600
            assert window.notebook.winfo_height() > 350
            assert window._rc48_status_bar.winfo_ismapped()
    finally:
        if window is not None:
            try:
                window.stop_event.set()
            except Exception:
                pass
        try:
            root.destroy()
        except tk.TclError:
            pass
        reset_path_cache_for_tests()
