from __future__ import annotations

from . import service as _service
from . import usage as _usage
from .contracts import AIRequest
from .openrouter_backend import OpenRouterBackend
from .settings import BACKEND_AGENT, BACKEND_OPENROUTER, BACKEND_ROUTER, load_backend_settings

_raw_backend_status = _service.backend_status
_raw_test_active_backend = _service.test_active_backend
_raw_usage_summary = _usage.usage_summary


def backend_status(backend: str | None = None, *, openrouter_key: str | None = None):
    """Compatibility facade for V2 UI and structured telemetry.

    The service-level zero-argument call remains the canonical structured telemetry
    API. The stable GUI historically asks for one backend at a time and expects a
    short human-readable string. RC49 keeps both contracts explicit instead of
    letting the GUI crash during startup after the telemetry refactor.
    """
    status = _raw_backend_status()
    if backend is None:
        return status

    selected = str(backend or "").strip().casefold()
    active = str(status.get("active_backend") or "").strip().casefold()
    marker = " · активний" if selected == active else ""

    if selected == BACKEND_OPENROUTER:
        configured = bool(str(openrouter_key or "").strip()) or bool(status.get("openrouter_configured"))
        state = "налаштовано" if configured else "API key не задано"
        return f"OpenRouter: {state}{marker}"

    if selected == BACKEND_ROUTER:
        router = status.get("router") if isinstance(status, dict) else None
        if isinstance(router, dict) and router.get("error"):
            return f"AI Router: помилка стану · {router.get('error')}{marker}"
        configured = int((router or {}).get("configured_providers") or 0) if isinstance(router, dict) else 0
        available = int((router or {}).get("available_providers") or 0) if isinstance(router, dict) else 0
        return f"AI Router: провайдерів {configured}, доступно {available}{marker}"

    if selected == BACKEND_AGENT:
        return f"Agent / Codex: {'активний' if selected == active else 'неактивний'}"

    return f"AI backend: {backend or 'невідомий'}{marker}"


def usage_summary(monthly_budget_usd: float | None = None, *, backend: str | None = None):
    """Keep telemetry and the stable GUI usage panel on one contract.

    New telemetry uses keyword-only backend filtering. The stable UI still passes
    the configured OpenRouter budget positionally and renders budget/remaining.
    """
    summary = dict(_raw_usage_summary(backend=backend))
    if monthly_budget_usd is None:
        return summary
    budget = max(0.0, float(monthly_budget_usd or 0.0))
    month_cost = float(summary.get("month_cost") or 0.0)
    summary["budget"] = budget
    summary["remaining"] = max(0.0, budget - month_cost)
    return summary


def test_active_backend(backend: str | None = None, *, timeout_seconds: int = 45) -> str:
    """Probe the requested backend without silently switching the active backend."""
    settings = load_backend_settings()
    selected = str(backend or settings.active_backend or BACKEND_ROUTER).strip().casefold()

    if selected == str(settings.active_backend or "").strip().casefold() and backend is None:
        return _raw_test_active_backend()

    if selected == BACKEND_OPENROUTER:
        return OpenRouterBackend(settings).probe()

    if selected == BACKEND_AGENT:
        request = AIRequest(
            prompt="Відповідай тільки словом OK.",
            max_output_tokens=16,
            task_timeout_seconds=max(3, int(timeout_seconds)),
        )
        result = _service._backend_for(BACKEND_AGENT, settings).run(request)
        return f"Agent backend працює: {result.label}"

    if selected == BACKEND_ROUTER:
        from ...ai_router import test_ai_router

        with _service._ROUTER_EXECUTION_LOCK:
            return test_ai_router()

    raise _service.AIServiceError(f"Невідомий AI backend: {selected}")


# The stable UI imports these functions directly from service.py / usage.py.
# Rebind the module exports once at package import so old GUI call sites and new
# telemetry call sites share one explicit compatibility contract.
_service.backend_status = backend_status
_service.test_active_backend = test_active_backend
_usage.usage_summary = usage_summary

active_backend = _service.active_backend
execute = _service.execute
run_ai_compat = _service.run_ai_compat

__all__ = [
    "active_backend",
    "backend_status",
    "execute",
    "run_ai_compat",
    "test_active_backend",
    "usage_summary",
]
