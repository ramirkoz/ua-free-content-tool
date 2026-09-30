from __future__ import annotations

import inspect
import threading
from typing import get_type_hints

import pytest


def test_rc51_direct_router_runtime_monkeypatch_module_is_removed() -> None:
    from pathlib import Path
    import content_agent.v2.ai as ai_package

    package_dir = Path(ai_package.__file__).resolve().parent
    assert not (package_dir / "direct_router_runtime.py").exists()


def test_rc51_ai_package_does_not_rebind_service_or_usage_functions() -> None:
    import content_agent.v2.ai as ai_package

    source = inspect.getsource(ai_package)
    assert "_service.backend_status =" not in source
    assert "_service.test_active_backend =" not in source
    assert "_usage.usage_summary =" not in source


def test_rc51_service_no_longer_installs_direct_router_runtime() -> None:
    from content_agent.v2.ai import service

    source = inspect.getsource(service)
    assert "install_direct_router_runtime" not in source
    assert "direct_router_runtime" not in source


def test_rc51_error_taxonomy_is_explicit_and_complete() -> None:
    from content_agent.v2.ai.contracts import AIErrorKind

    assert {item.value for item in AIErrorKind} == {
        "auth",
        "quota",
        "configuration",
        "model",
        "temporary",
        "bad_response",
        "validation",
        "request_too_large",
        "timeout",
        "cancelled",
    }


def test_rc51_pre_cancelled_request_fails_closed() -> None:
    from content_agent.v2.ai.contracts import AIErrorKind, AIRequest
    from content_agent.v2.ai.service import AIServiceError, execute_request

    cancel = threading.Event()
    cancel.set()
    with pytest.raises(AIServiceError) as caught:
        execute_request(AIRequest(prompt="test", cancel_event=cancel))
    assert caught.value.kind is AIErrorKind.CANCELLED


def test_rc51_unknown_backend_is_configuration_error() -> None:
    from content_agent.v2.ai.contracts import AIErrorKind
    from content_agent.v2.ai.service import AIServiceError, _backend_for

    with pytest.raises(AIServiceError) as caught:
        _backend_for("not-a-backend", object())
    assert caught.value.kind is AIErrorKind.CONFIGURATION


def test_rc51_usage_budget_is_native_contract(monkeypatch) -> None:
    from content_agent.v2.ai import usage

    monkeypatch.setattr(usage, "_iter_events", lambda: ())
    raw = usage.usage_summary(backend="openrouter")
    assert "budget" not in raw
    ui = usage.usage_summary(20.0, backend="openrouter")
    assert ui["budget"] == 20.0
    assert ui["remaining"] == 20.0


def test_rc51_gateway_is_the_composed_ai_entrypoint() -> None:
    from content_agent.app.container import AppServices
    from content_agent.v2.ai.gateway import AIGateway

    assert get_type_hints(AppServices)["ai"] is AIGateway


def test_rc51_gateway_runs_typed_requests(monkeypatch) -> None:
    from content_agent.v2.ai import gateway
    from content_agent.v2.ai.contracts import AIRequest, UnifiedAIResult

    expected = UnifiedAIResult(
        text="OK",
        backend="router",
        provider="fake",
        model="fake-model",
        label="fake",
    )
    monkeypatch.setattr("content_agent.v2.ai.service.execute_request", lambda request: expected)
    result = gateway.AIGateway().run(AIRequest(prompt="test"))
    assert result is expected


def test_rc51_ui_still_has_one_canonical_ai_tab_builder() -> None:
    from content_agent.v2.ui.window import MainWindow

    source = inspect.getsource(MainWindow._build_v2_ai_tab)
    assert 'self.notebook.add(tab, text="AI")' in source
    assert "OpenRouter" in source
    assert "Наш AI Router" in source
    assert "Agent" in source
