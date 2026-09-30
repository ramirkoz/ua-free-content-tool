from __future__ import annotations

import sys

import pytest


def test_rc49_stable_window_exposes_ai_provider_callbacks() -> None:
    from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow

    assert callable(getattr(MainWindow, "save_ai_provider_keys", None))
    assert callable(getattr(MainWindow, "test_ai_router_ui", None))


def test_rc49_main_keeps_stable_rc44_shell() -> None:
    from content_agent import main
    from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow

    assert main.MainWindow is MainWindow


def test_rc49_ai_status_compat_contract_keeps_structured_telemetry(monkeypatch) -> None:
    from content_agent.v2 import ai

    fake = {
        "active_backend": "router",
        "openrouter_configured": False,
        "router": {"configured_providers": 3, "available_providers": 2, "rows": []},
    }
    monkeypatch.setattr(ai, "_raw_backend_status", lambda: fake)

    assert ai.backend_status() is fake
    assert "доступно 2" in ai.backend_status("router")
    assert "API key не задано" in ai.backend_status("openrouter", openrouter_key="")
    assert "налаштовано" in ai.backend_status("openrouter", openrouter_key="test-key")


def test_rc49_refresh_ai_status_accepts_stable_ui_calls(monkeypatch) -> None:
    from content_agent.v2 import ai
    from content_agent.v2.ai.settings import AIBackendSettings, BACKEND_ROUTER
    from content_agent.v2.ui import window as window_module
    from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow

    class Var:
        def __init__(self, value=""):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    settings = AIBackendSettings(active_backend=BACKEND_ROUTER)
    monkeypatch.setattr(window_module, "load_backend_settings", lambda: settings)
    monkeypatch.setattr(window_module, "provider_health_text", lambda: "Router health OK")
    monkeypatch.setattr(window_module, "inspect_codex_cached", lambda: "Codex cached OK")
    monkeypatch.setattr(window_module, "usage_summary", lambda **_kwargs: {"requests": 0})
    monkeypatch.setattr(ai, "_raw_backend_status", lambda: {
        "active_backend": BACKEND_ROUTER,
        "openrouter_configured": False,
        "router": {"configured_providers": 1, "available_providers": 1, "rows": []},
    })

    window = object.__new__(MainWindow)
    window.v2_backend_settings = settings
    window.v2_backend_var = Var(BACKEND_ROUTER)
    window.v2_ai_status_var = Var()
    window.v2_openrouter_key_var = Var("")
    window.v2_openrouter_status_var = Var()
    window.v2_router_status_var = Var()
    window.v2_agent_status_var = Var()
    window.v2_usage_var = Var()

    MainWindow.refresh_v2_ai_status(window)

    assert "AI Router" in str(window.v2_ai_status_var.get())
    assert "OpenRouter" in str(window.v2_openrouter_status_var.get())
    assert "Router health OK" == window.v2_router_status_var.get()


@pytest.mark.skipif(sys.platform != "win32", reason="Tk smoke is exercised by the RC49 Windows gate")
def test_rc49_full_ai_tab_builds_on_windows(monkeypatch) -> None:
    import tkinter as tk
    from tkinter import ttk

    from content_agent.v2 import ai
    from content_agent.v2.ai.settings import AIBackendSettings, BACKEND_ROUTER
    from content_agent.v2.ui import window as window_module
    from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow

    settings = AIBackendSettings(active_backend=BACKEND_ROUTER)
    monkeypatch.setattr(window_module, "load_backend_settings", lambda: settings)
    monkeypatch.setattr(window_module, "load_provider_secrets", lambda: type("Secrets", (), {
        "gemini_api_key": "",
        "nvidia_api_key": "",
        "groq_api_key": "",
        "cloudflare_account_id": "",
        "cloudflare_api_token": "",
        "codex_enabled": False,
        "local_enabled": False,
    })())
    monkeypatch.setattr(ai, "_raw_backend_status", lambda: {
        "active_backend": BACKEND_ROUTER,
        "openrouter_configured": False,
        "router": {"configured_providers": 0, "available_providers": 0, "rows": []},
    })

    root = tk.Tk()
    root.withdraw()
    try:
        window = object.__new__(MainWindow)
        window.root = root
        window.notebook = ttk.Notebook(root)
        window.v2_backend_settings = settings
        window.v2_backend_var = tk.StringVar(master=root, value=BACKEND_ROUTER)
        window.v2_openrouter_key_var = tk.StringVar(master=root, value="")
        window.v2_openrouter_budget_var = tk.StringVar(master=root, value="5.00")
        window.v2_ai_status_var = tk.StringVar(master=root, value="AI V2: init")
        window.v2_openrouter_status_var = tk.StringVar(master=root, value="")
        window.v2_router_status_var = tk.StringVar(master=root, value="")
        window.v2_agent_status_var = tk.StringVar(master=root, value="")

        MainWindow._build_v2_ai_tab(window)
        root.update_idletasks()

        assert len(window.notebook.tabs()) == 1
        assert hasattr(window, "ai_provider_vars")
        assert set(window.ai_provider_vars) == {
            "gemini_api_key",
            "nvidia_api_key",
            "groq_api_key",
            "cloudflare_account_id",
            "cloudflare_api_token",
        }
    finally:
        root.destroy()
