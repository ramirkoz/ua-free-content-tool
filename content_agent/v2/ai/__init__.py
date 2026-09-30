from __future__ import annotations

from . import service as _service
from . import usage as _usage
from .settings import BACKEND_AGENT, BACKEND_OPENROUTER, BACKEND_ROUTER

# Compatibility hooks retained for RC49 callers/tests. They are ordinary package
# wrappers now; RC51 no longer rebinds service.py or usage.py at import time.
_raw_backend_status = _service._structured_backend_status
_raw_usage_summary = _usage.usage_summary


def backend_status(backend: str | None = None, *, openrouter_key: str | None = None):
    status = _raw_backend_status()
    if backend is None:
        return status
    selected = str(backend or "").strip().casefold()
    active = str(status.get("active_backend") or "").strip().casefold()
    marker = " · активний" if selected == active else ""
    if selected == BACKEND_OPENROUTER:
        configured = bool(str(openrouter_key or "").strip()) or bool(status.get("openrouter_configured"))
        return f"OpenRouter: {'налаштовано' if configured else 'API key не задано'}{marker}"
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
    summary = dict(_raw_usage_summary(backend=backend))
    if monthly_budget_usd is None:
        return summary
    budget = max(0.0, float(monthly_budget_usd or 0.0))
    summary["budget"] = budget
    summary["remaining"] = max(0.0, budget - float(summary.get("month_cost") or 0.0))
    return summary


active_backend = _service.active_backend
execute = _service.execute
run_ai_compat = _service.run_ai_compat
test_active_backend = _service.test_active_backend

__all__ = [
    "active_backend",
    "backend_status",
    "execute",
    "run_ai_compat",
    "test_active_backend",
    "usage_summary",
]
