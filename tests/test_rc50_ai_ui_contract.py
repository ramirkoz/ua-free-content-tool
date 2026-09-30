from __future__ import annotations

from content_agent.v2.ai import service
from content_agent.v2.ai.settings import (
    AIBackendSettings,
    BACKEND_AGENT,
    BACKEND_OPENROUTER,
    BACKEND_ROUTER,
)
from content_agent.v2.ai.usage import usage_summary


def test_backend_status_supports_telemetry_and_ui_shapes(monkeypatch) -> None:
    settings = AIBackendSettings(
        active_backend=BACKEND_OPENROUTER,
        openrouter_strategy="balanced",
        openrouter_monthly_budget_usd=10.0,
    )
    monkeypatch.setattr(service, "load_backend_settings", lambda: settings)
    monkeypatch.setattr(service.OpenRouterBackend, "configured", lambda self: False)
    snapshot = service.backend_status()
    assert isinstance(snapshot, dict)
    assert snapshot["active_backend"] == BACKEND_OPENROUTER
    text = service.backend_status(BACKEND_OPENROUTER, openrouter_key="secret")
    assert isinstance(text, str)
    assert "OpenRouter" in text
    assert "налаштовано" in text


def test_test_active_backend_accepts_explicit_backend(monkeypatch) -> None:
    settings = AIBackendSettings(active_backend=BACKEND_ROUTER)
    monkeypatch.setattr(service, "load_backend_settings", lambda: settings)
    monkeypatch.setattr(service.OpenRouterBackend, "probe", lambda self: "openrouter-ok")
    assert service.test_active_backend(BACKEND_OPENROUTER) == "openrouter-ok"


def test_usage_summary_keeps_ui_budget_contract(monkeypatch) -> None:
    monkeypatch.setattr("content_agent.v2.ai.usage._iter_events", lambda: ())
    summary = usage_summary(25.0)
    assert summary["budget"] == 25.0
    assert summary["remaining"] == 25.0
    filtered = usage_summary(backend="openrouter")
    assert "month_requests" in filtered


def test_v2_ai_window_calls_supported_service_contracts() -> None:
    import inspect
    from content_agent.v2.ui.window import MainWindow

    source = inspect.getsource(MainWindow.refresh_v2_ai_status)
    assert "backend_status(settings.active_backend)" in source
    assert "openrouter_key=" in source
    assert "usage_summary(settings.openrouter_monthly_budget_usd)" in source
    # All three calls are intentionally supported by the RC50 service contract.
    assert isinstance(service.backend_status(BACKEND_ROUTER), str)
