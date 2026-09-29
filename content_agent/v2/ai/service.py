from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable

from .contracts import AIBackend, AIRequest, UnifiedAIResult
from .direct_router_runtime import install_direct_router_runtime
from .openrouter_backend import OpenRouterBackend, recent_events
from .settings import BACKEND_AGENT, BACKEND_OPENROUTER, BACKEND_ROUTER, load_backend_settings


logger = logging.getLogger("content_agent.v2.ai_service")

# Historical Router call sites are still normalized here while the stable V2
# service owns routing/timeout/cancel semantics.  This is the single remaining
# compatibility boundary; UI code must not import historical router modules.
install_direct_router_runtime()


class AIServiceError(RuntimeError):
    pass


_LOCK = threading.RLock()
_ROUTER_EXECUTION_LOCK = threading.RLock()
_LAST_RESULT: UnifiedAIResult | None = None
_PROCESS_STARTED_AT = datetime.now().astimezone().isoformat(timespec="seconds")


def _legacy_result_to_unified(result: object, backend: str) -> UnifiedAIResult:
    return UnifiedAIResult(
        text=str(getattr(result, "text", "") or ""),
        backend=backend,
        provider=str(getattr(result, "provider", backend) or backend),
        model=str(getattr(result, "model", "") or ""),
        label=str(getattr(result, "label", "") or backend),
        attempted=tuple(getattr(result, "attempted", ()) or ()),
    )


def _normalized(values: object) -> set[str]:
    return {
        str(value or "").strip().casefold()
        for value in (values or ())
        if str(value or "").strip()
    }


class _OpenRouterAIBackend:
    name = BACKEND_OPENROUTER

    def __init__(self, settings: object) -> None:
        self.settings = settings

    def run(self, request: AIRequest) -> UnifiedAIResult:
        if "openrouter" in _normalized(request.skip_providers):
            raise AIServiceError("OpenRouter пропущено safety contract цього AI-завдання.")
        timeout = int(request.task_timeout_seconds or request.cloud_timeout_seconds or 120)
        return OpenRouterBackend(self.settings).run(
            request.prompt,
            validator=request.validator,
            max_output_tokens=request.max_output_tokens,
            timeout_seconds=timeout,
            skip_models=tuple(_normalized(request.skip_models)),
        )


class _AgentAIBackend:
    name = BACKEND_AGENT

    def run(self, request: AIRequest) -> UnifiedAIResult:
        skipped_providers = _normalized(request.skip_providers)
        skipped_models = _normalized(request.skip_models)
        if skipped_providers.intersection({"agent", "codex"}) or "codex-chatgpt" in skipped_models:
            raise AIServiceError("Codex / ChatGPT пропущено safety contract цього AI-завдання.")
        from ... import ai_router as legacy

        timeout = max(3, int(request.task_timeout_seconds or request.cloud_timeout_seconds or 120))
        started = time.monotonic()
        try:
            text = str(legacy._invoke_codex_limited(request.prompt, timeout)).strip()
        except Exception as exc:
            if request.cancel_event is not None and bool(
                getattr(request.cancel_event, "is_set", lambda: False)()
            ):
                raise AIServiceError("AI-завдання скасовано.") from exc
            raise AIServiceError(f"Agent backend (Codex) не завершив запит: {exc}") from exc
        if not text:
            raise AIServiceError("Agent backend повернув порожню відповідь.")
        if request.cancel_event is not None and bool(
            getattr(request.cancel_event, "is_set", lambda: False)()
        ):
            raise AIServiceError("AI-завдання скасовано.")
        if request.validator is not None:
            request.validator(text)
        return UnifiedAIResult(
            text=text,
            backend=BACKEND_AGENT,
            provider="codex",
            model="codex-chatgpt",
            label=f"Codex / ChatGPT · {time.monotonic()-started:.1f}s",
            attempted=("codex:codex-chatgpt",),
        )


class _RouterAIBackend:
    name = BACKEND_ROUTER

    def run(self, request: AIRequest) -> UnifiedAIResult:
        from ... import ai_router as legacy

        with _ROUTER_EXECUTION_LOCK:
            return _legacy_result_to_unified(
                legacy.run_ai_router(
                    request.prompt,
                    validator=request.validator,
                    max_output_tokens=request.max_output_tokens,
                    local_prompt=request.local_prompt,
                    local_max_output_tokens=request.local_max_output_tokens,
                    local_timeout_seconds=request.local_timeout_seconds,
                    local_repair=request.local_repair,
                    cloud_timeout_seconds=request.cloud_timeout_seconds,
                    task_timeout_seconds=request.task_timeout_seconds,
                    skip_providers=request.skip_providers,
                    skip_models=request.skip_models,
                    suppress_provider_on_quota=request.suppress_provider_on_quota,
                    cancel_event=request.cancel_event,
                ),
                BACKEND_ROUTER,
            )


def _backend_for(name: str, settings: object) -> AIBackend:
    if name == BACKEND_OPENROUTER:
        return _OpenRouterAIBackend(settings)
    if name == BACKEND_AGENT:
        return _AgentAIBackend()
    return _RouterAIBackend()


def execute_request(request: AIRequest) -> UnifiedAIResult:
    """Execute one typed AI request through the selected backend contract."""
    global _LAST_RESULT
    if request.cancel_event is not None and bool(
        getattr(request.cancel_event, "is_set", lambda: False)()
    ):
        raise AIServiceError("AI-завдання скасовано.")

    settings = load_backend_settings()
    backend_name = str(settings.active_backend or BACKEND_ROUTER)
    logger.info(
        "AI V2 execute backend=%s task=%s tier=%s max_output_tokens=%s",
        backend_name,
        request.task.value,
        request.quality_tier.value,
        request.max_output_tokens,
    )
    result = _backend_for(backend_name, settings).run(request)
    with _LOCK:
        _LAST_RESULT = result
    return result


def execute(
    prompt: str,
    *,
    validator: Callable[[str], object] | None = None,
    max_output_tokens: int = 4096,
    local_prompt: str | None = None,
    local_max_output_tokens: int | None = None,
    local_timeout_seconds: int = 120,
    local_repair: bool = True,
    cloud_timeout_seconds: int = 120,
    task_timeout_seconds: int | None = None,
    skip_providers=(),
    skip_models=(),
    suppress_provider_on_quota: bool = False,
    cancel_event: object | None = None,
) -> UnifiedAIResult:
    return execute_request(
        AIRequest(
            prompt=str(prompt),
            validator=validator,
            max_output_tokens=int(max_output_tokens),
            local_prompt=local_prompt,
            local_max_output_tokens=local_max_output_tokens,
            local_timeout_seconds=int(local_timeout_seconds),
            local_repair=bool(local_repair),
            cloud_timeout_seconds=int(cloud_timeout_seconds),
            task_timeout_seconds=task_timeout_seconds,
            skip_providers=tuple(skip_providers or ()),
            skip_models=tuple(skip_models or ()),
            suppress_provider_on_quota=bool(suppress_provider_on_quota),
            cancel_event=cancel_event,
        )
    )


def run_ai_compat(*args, **kwargs):
    unified = execute(*args, **kwargs)
    from ...ai_router import AIResult

    priority = 0 if unified.backend == BACKEND_OPENROUTER else 1 if unified.backend == BACKEND_AGENT else 2
    return AIResult(
        unified.text,
        unified.provider,
        unified.model,
        unified.label,
        priority,
        unified.attempted,
    )


def active_backend() -> str:
    return load_backend_settings().active_backend


def last_result() -> UnifiedAIResult | None:
    with _LOCK:
        return _LAST_RESULT


def _structured_backend_status() -> dict[str, object]:
    settings = load_backend_settings()
    status: dict[str, object] = {
        "active_backend": settings.active_backend,
        "process_started_at": _PROCESS_STARTED_AT,
        "openrouter_configured": OpenRouterBackend(settings).configured(),
        "openrouter_strategy": settings.openrouter_strategy,
        "openrouter_budget_usd": settings.openrouter_monthly_budget_usd,
    }
    try:
        from ...ai_router import provider_health_rows

        with _ROUTER_EXECUTION_LOCK:
            rows = provider_health_rows()
        configured = [row for row in rows if bool(row.get("configured"))]
        available = [row for row in configured if int(row.get("available_slots") or 0) > 0]
        status["router"] = {
            "configured_providers": len(configured),
            "available_providers": len(available),
            "rows": rows,
        }
    except Exception as exc:
        status["router"] = {"error": str(exc)[:500]}
    try:
        from .usage import usage_summary

        status["openrouter_usage"] = usage_summary(backend="openrouter")
    except Exception:
        status["openrouter_usage"] = {}
    try:
        status["openrouter_recent_events"] = recent_events(16)
    except Exception:
        status["openrouter_recent_events"] = []
    current = last_result()
    if current is not None:
        status["last_backend"] = current.backend
        status["last_model"] = current.model
        status["last_label"] = current.label
    return status


def backend_status(
    backend: str | None = None,
    *,
    openrouter_key: str | None = None,
) -> dict[str, object] | str:
    """Canonical status API plus the stable UI text view.

    With no backend argument it returns structured telemetry.  The optional backend
    form is retained as a UI compatibility view so historical V2 widgets cannot
    crash startup when service internals evolve.
    """
    status = _structured_backend_status()
    if backend is None:
        return status
    selected = str(backend or BACKEND_ROUTER).strip().casefold()
    active = str(status.get("active_backend") or BACKEND_ROUTER)
    marker = "активний" if selected == active else "резерв"
    if selected == BACKEND_OPENROUTER:
        configured = bool(str(openrouter_key or "").strip()) or bool(status.get("openrouter_configured"))
        return f"OpenRouter: {'налаштовано' if configured else 'не налаштовано'} · {marker}"
    if selected == BACKEND_AGENT:
        try:
            from ...codex_runtime import inspect_codex_cached

            info = inspect_codex_cached(max_age_seconds=20.0)
            ready = bool(info.installed and info.authenticated)
            return f"Agent / Codex: {'готовий' if ready else info.detail} · {marker}"
        except Exception as exc:
            return f"Agent / Codex: стан недоступний · {exc}"
    router = status.get("router") if isinstance(status.get("router"), dict) else {}
    if isinstance(router, dict) and router.get("error"):
        return f"AI Router: помилка стану · {router['error']}"
    configured = int(router.get("configured_providers", 0) or 0) if isinstance(router, dict) else 0
    available = int(router.get("available_providers", 0) or 0) if isinstance(router, dict) else 0
    return f"AI Router: {available}/{configured} доступні · {marker}"


def test_active_backend(
    backend: str | None = None,
    *,
    timeout_seconds: int = 45,
) -> str:
    """Probe an explicit backend or, by default, the currently selected backend."""
    settings = load_backend_settings()
    selected = str(backend or settings.active_backend or BACKEND_ROUTER)
    if selected == BACKEND_OPENROUTER:
        return OpenRouterBackend(settings).probe()
    if selected == BACKEND_AGENT:
        from ... import ai_router as legacy

        text = str(legacy._invoke_codex_limited("Відповідай тільки словом OK.", max(3, int(timeout_seconds)))).strip()
        if not text:
            raise AIServiceError("Agent backend повернув порожню відповідь під час перевірки.")
        return "Agent backend працює: Codex / ChatGPT"
    from ...ai_router import test_ai_router

    with _ROUTER_EXECUTION_LOCK:
        return test_ai_router()


__all__ = [
    "AIServiceError",
    "active_backend",
    "backend_status",
    "execute",
    "execute_request",
    "last_result",
    "run_ai_compat",
    "test_active_backend",
]
