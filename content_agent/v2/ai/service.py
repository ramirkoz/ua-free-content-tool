from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable

from .contracts import AIBackend, AIErrorKind, AIRequest, UnifiedAIResult
from .openrouter_backend import OpenRouterBackend, recent_events
from .router_backend import CanonicalRouterBackend
from .settings import BACKEND_AGENT, BACKEND_OPENROUTER, BACKEND_ROUTER, load_backend_settings


logger = logging.getLogger("content_agent.v2.ai_service")


class AIServiceError(RuntimeError):
    """Canonical AI failure surfaced by the V2 gateway."""

    def __init__(self, message: str, *, kind: AIErrorKind | str = AIErrorKind.TEMPORARY) -> None:
        super().__init__(message)
        try:
            self.kind = AIErrorKind(str(kind))
        except ValueError:
            self.kind = AIErrorKind.TEMPORARY


_LOCK = threading.RLock()
# Router state is a read/modify/write JSON contract. Serialize Router execution so
# parallel jobs cannot overwrite cooldown/model-health state. Other backends remain
# independent.
_ROUTER_EXECUTION_LOCK = threading.RLock()
_LAST_RESULT: UnifiedAIResult | None = None
_PROCESS_STARTED_AT = datetime.now().astimezone().isoformat(timespec="seconds")


def _cancelled(request: AIRequest) -> bool:
    return bool(
        request.cancel_event is not None
        and getattr(request.cancel_event, "is_set", lambda: False)()
    )


def _require_not_cancelled(request: AIRequest) -> None:
    if _cancelled(request):
        raise AIServiceError("AI-завдання скасовано.", kind=AIErrorKind.CANCELLED)


def _normalized(values: object) -> set[str]:
    return {
        str(value or "").strip().casefold()
        for value in (values or ())
        if str(value or "").strip()
    }


def _error_kind(exc: BaseException) -> AIErrorKind:
    explicit = str(getattr(exc, "kind", "") or "").strip().casefold()
    aliases = {
        "auth": AIErrorKind.AUTH,
        "quota": AIErrorKind.QUOTA,
        "configuration": AIErrorKind.CONFIGURATION,
        "model": AIErrorKind.MODEL,
        "temporary": AIErrorKind.TEMPORARY,
        "bad_response": AIErrorKind.BAD_RESPONSE,
        "validation": AIErrorKind.VALIDATION,
        "request_too_large": AIErrorKind.REQUEST_TOO_LARGE,
        "timeout": AIErrorKind.TIMEOUT,
        "cancelled": AIErrorKind.CANCELLED,
    }
    if explicit in aliases:
        return aliases[explicit]
    text = str(exc or "").casefold()
    if any(token in text for token in ("скасовано", "cancelled", "canceled")):
        return AIErrorKind.CANCELLED
    if any(token in text for token in ("timeout", "timed out", "перевищено ліміт")):
        return AIErrorKind.TIMEOUT
    if any(token in text for token in ("unauthorized", "authentication", "http 401", "http 403", "не авториз")):
        return AIErrorKind.AUTH
    if any(token in text for token in ("quota", "usage limit", "billing", "daily quota")):
        return AIErrorKind.QUOTA
    if any(token in text for token in ("порожн", "invalid json", "bad_response", "reasoning but no final")):
        return AIErrorKind.BAD_RESPONSE
    return AIErrorKind.TEMPORARY


class _OpenRouterAIBackend:
    name = BACKEND_OPENROUTER

    def __init__(self, settings: object) -> None:
        self.settings = settings

    def run(self, request: AIRequest) -> UnifiedAIResult:
        _require_not_cancelled(request)
        if "openrouter" in _normalized(request.skip_providers):
            raise AIServiceError(
                "OpenRouter пропущено safety contract цього AI-завдання.",
                kind=AIErrorKind.VALIDATION,
            )
        timeout = max(3, int(request.task_timeout_seconds or request.cloud_timeout_seconds or 120))
        try:
            result = OpenRouterBackend(self.settings).run(
                request.prompt,
                validator=request.validator,
                max_output_tokens=request.max_output_tokens,
                timeout_seconds=timeout,
                skip_models=tuple(_normalized(request.skip_models)),
            )
        except Exception as exc:
            if _cancelled(request):
                raise AIServiceError("AI-завдання скасовано.", kind=AIErrorKind.CANCELLED) from exc
            raise AIServiceError(str(exc), kind=_error_kind(exc)) from exc
        _require_not_cancelled(request)
        return result


class _AgentAIBackend:
    name = BACKEND_AGENT

    def run(self, request: AIRequest) -> UnifiedAIResult:
        _require_not_cancelled(request)
        skipped_providers = _normalized(request.skip_providers)
        skipped_models = _normalized(request.skip_models)
        if skipped_providers.intersection({"agent", "codex"}) or "codex-chatgpt" in skipped_models:
            raise AIServiceError(
                "Codex / ChatGPT пропущено safety contract цього AI-завдання.",
                kind=AIErrorKind.VALIDATION,
            )
        from ... import ai_router as legacy

        timeout = max(3, int(request.task_timeout_seconds or request.cloud_timeout_seconds or 120))
        started = time.monotonic()
        try:
            text = str(legacy._invoke_codex_limited(request.prompt, timeout)).strip()
        except Exception as exc:
            if _cancelled(request):
                raise AIServiceError("AI-завдання скасовано.", kind=AIErrorKind.CANCELLED) from exc
            raise AIServiceError(f"Agent backend (Codex) не завершив запит: {exc}", kind=_error_kind(exc)) from exc
        _require_not_cancelled(request)
        if not text:
            raise AIServiceError("Agent backend повернув порожню відповідь.", kind=AIErrorKind.BAD_RESPONSE)
        if request.validator is not None:
            try:
                request.validator(text)
            except Exception as exc:
                raise AIServiceError(f"Agent backend: відповідь не пройшла перевірку: {exc}", kind=AIErrorKind.VALIDATION) from exc
        return UnifiedAIResult(
            text=text,
            backend=BACKEND_AGENT,
            provider="codex",
            model="codex-chatgpt",
            label=f"Codex / ChatGPT · {time.monotonic()-started:.1f}s",
            attempted=("codex:codex-chatgpt",),
        )


def _backend_for(name: str, settings: object) -> AIBackend:
    if name == BACKEND_OPENROUTER:
        return _OpenRouterAIBackend(settings)
    if name == BACKEND_AGENT:
        return _AgentAIBackend()
    if name == BACKEND_ROUTER:
        return CanonicalRouterBackend()
    raise AIServiceError(f"Невідомий AI backend: {name}", kind=AIErrorKind.CONFIGURATION)


def execute_request(request: AIRequest) -> UnifiedAIResult:
    """Execute one canonical typed AI request through exactly one selected backend."""
    global _LAST_RESULT
    _require_not_cancelled(request)
    settings = load_backend_settings()
    backend_name = str(settings.active_backend or BACKEND_ROUTER).strip().casefold()
    logger.info(
        "AI V2 execute backend=%s task=%s tier=%s max_output_tokens=%s",
        backend_name,
        request.task.value,
        request.quality_tier.value,
        request.max_output_tokens,
    )
    backend = _backend_for(backend_name, settings)
    try:
        if backend_name == BACKEND_ROUTER:
            with _ROUTER_EXECUTION_LOCK:
                result = backend.run(request)
        else:
            result = backend.run(request)
    except AIServiceError:
        raise
    except Exception as exc:
        if _cancelled(request):
            raise AIServiceError("AI-завдання скасовано.", kind=AIErrorKind.CANCELLED) from exc
        raise AIServiceError(str(exc), kind=_error_kind(exc)) from exc
    _require_not_cancelled(request)
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
    """Compatibility signature that builds the canonical AIRequest."""
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
    """Legacy return-shape shim; execution still goes through the V2 gateway contract."""
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


def backend_status(backend: str | None = None, *, openrouter_key: str | None = None):
    """Structured status for telemetry, or one human-readable backend line for UI."""
    status = _structured_backend_status()
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


def test_active_backend(backend: str | None = None, *, timeout_seconds: int = 45) -> str:
    """Probe the requested backend without changing the selected backend."""
    settings = load_backend_settings()
    selected = str(backend or settings.active_backend or BACKEND_ROUTER).strip().casefold()
    if selected == BACKEND_OPENROUTER:
        return OpenRouterBackend(settings).probe()
    request = AIRequest(
        prompt="Відповідай тільки словом OK.",
        max_output_tokens=16,
        task_timeout_seconds=max(3, int(timeout_seconds)),
    )
    if selected == BACKEND_AGENT:
        result = _backend_for(BACKEND_AGENT, settings).run(request)
        return f"Agent backend працює: {result.label}"
    if selected == BACKEND_ROUTER:
        with _ROUTER_EXECUTION_LOCK:
            result = _backend_for(BACKEND_ROUTER, settings).run(request)
        return f"AI Router працює: {result.label}"
    raise AIServiceError(f"Невідомий AI backend: {selected}", kind=AIErrorKind.CONFIGURATION)


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
