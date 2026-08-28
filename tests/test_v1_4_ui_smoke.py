from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

import pytest

from content_agent.config import AppConfig
from content_agent.database_v1_4_runtime import Database
from content_agent.ui.v1_4_window import MainWindow


@pytest.mark.skipif(sys.platform != "win32", reason="Tk desktop smoke is validated on Windows CI")
def test_v14_main_window_constructs_with_destination_tabs(tmp_path: Path, isolated_data) -> None:
    root = tk.Tk()
    root.withdraw()
    window = None
    try:
        db = Database(tmp_path / "content.sqlite3")
        config = AppConfig()
        window = MainWindow(root, db, config)
        root.update_idletasks()
        assert "__all__" in window.queue_trees
        assert "__all__" in window.history_trees
        assert window.VERSION_LABEL == "1.4.0-rc1"
    finally:
        if window is not None:
            window.stop_event.set()
        root.destroy()
