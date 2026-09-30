from __future__ import annotations

import tkinter as tk


def test_full_v2_window_builds_and_refreshes_ai_contract(tmp_path, monkeypatch) -> None:
    from content_agent.app.container import build_services
    from content_agent.config import AppConfig
    from content_agent.v2.storage.factory import create_database
    from content_agent.v2.supervisor.resilient_runtime import ResilientSupervisorRuntime
    from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow

    monkeypatch.setattr(ResilientSupervisorRuntime, "start", lambda self: None)
    root = tk.Tk()
    root.withdraw()
    window = None
    try:
        database = create_database(tmp_path / "content_agent.sqlite3")
        services = build_services(config=AppConfig(), database=database)
        window = MainWindow(root, services)
        window._ui_ready = True
        window.refresh_v2_ai_status()
        root.update_idletasks()

        tabs = [str(window.notebook.tab(tab, "text")) for tab in window.notebook.tabs()]
        for required in ("Вхідні", "Публікація", "AI", "Стан системи", "Дані й backup", "Платформи"):
            assert required in tabs
        assert "backend_status() takes" not in window.v2_ai_status_var.get()
        assert callable(window.save_ai_provider_keys)
        assert callable(window.test_ai_router_ui)
        assert window.operation_progress.winfo_exists()
        assert window.inbox_controller is not None
        assert window.data_tab_controller is not None
        assert window.platforms_tab_controller is not None
    finally:
        if window is not None:
            window.stop_event.set()
        root.destroy()
