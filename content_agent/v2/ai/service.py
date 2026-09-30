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

# Compatibility transport bridge. RC50 keeps this active until the direct Router
# transport is moved into ai_router.py itself; the public V2 contract below is stable.
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


def _backend_status_dict() -> dict[str, object]:
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


def backend_status_text(name: str, *, openrouter_key: str | None = None) -> str:
    """Human-readable status for one backend, used by Tk without hidden probes.

    This function is deliberately side-effect free: opening the AI tab must never
    perform a live provider request or mutate cooldown state.
    """
    target = str(name or "").strip().casefold()
    status = _backend_status_dict()
    settings = load_backend_settings()
    if target == BACKEND_OPENROUTER:
        configured = bool(str(openrouter_key or "").strip()) or bool(status.get("openrouter_configured"))
        return (
            "OpenRouter: налаштовано · strategy " + str(settings.openrouter_strategy)
            if configured
            else "OpenRouter: API key не налаштовано"
        )
    if target == BACKEND_AGENT:
        try:
            from ...codex_runtime import peek_codex_status_cache

            cached = peek_codex_status_cache()
            if cached is None:
                return "Agent / Codex: стан ще не перевірено"
            if bool(getattr(cached, "installed", False)) and bool(getattr(cached, "authenticated", False)):
                return "Agent / Codex: готовий"
            return "Agent / Codex: " + str(getattr(cached, "detail", "не готовий") or "не готовий")
        except Exception as exc:
            return f"Agent / Codex: помилка стану · {exc}"
    router = status.get("router")
    if isinstance(router, dict):
        if router.get("error"):
            return "AI Router: помилка стану · " + str(router.get("error"))
        configured = int(router.get("configured_providers") or 0)
        available = int(router.get("available_providers") or 0)
        return f"AI Router: {available}/{configured} провайдерів доступні"
    return "AI Router: стан невідомий"


def backend_status(name: str | None = None, *, openrouter_key: str | None = None):
    """Stable status API.

    No arguments returns structured telemetry. The optional arguments remain a
    compatibility bridge for RC49-era UI code so a stale widget cannot crash the
    whole application while RC50 completes the UI migration.
    """
    if name is None:
        return _backend_status_dict()
    return backend_status_text(name, openrouter_key=openrouter_key)


def test_active_backend() -> str:
    settings = load_backend_settings()
    if settings.active_backend == BACKEND_OPENROUTER:
        return OpenRouterBackend(settings).probe()
    if settings.active_backend == BACKEND_AGENT:
        result = execute("Відповідай тільки словом OK.", max_output_tokens=16, task_timeout_seconds=45)
        return f"Agent backend працює: {result.label}"
    from ...ai_router import test_ai_router

    with _ROUTER_EXECUTION_LOCK:
        return test_ai_router()


__all__ = [
    "AIServiceError",
    "active_backend",
    "backend_status",
    "backend_status_text",
    "execute",
    "execute_request",
    "last_result",
    "run_ai_compat",
    "test_active_backend",
]
