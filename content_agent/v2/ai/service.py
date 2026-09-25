from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable

from .contracts import UnifiedAIResult
from .direct_router_runtime import install_direct_router_runtime
from .openrouter_backend import OpenRouterBackend, recent_events
from .settings import BACKEND_AGENT, BACKEND_OPENROUTER, BACKEND_ROUTER, load_backend_settings


logger = logging.getLogger("content_agent.v2.ai_service")

# The V2 shell imports this module before rendering AI health. Install the direct
# provider recovery layer here so UI, supervisor and runtime all see one router.
install_direct_router_runtime()


class AIServiceError(RuntimeError):
    pass


_LOCK = threading.RLock()
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
    """Single V2 execution gate.

    Backend choice remains explicit. RC8 changes the direct Router itself: direct
    Gemini/Groq/NVIDIA/Cloudflare calls now use paced transport, short retry and
    reviewed model fallbacks rather than treating one transient response as a dead
    provider.
    """
    global _LAST_RESULT
    settings = load_backend_settings()
    backend = settings.active_backend
    logger.info("AI V2 execute backend=%s max_output_tokens=%s", backend, max_output_tokens)

    if backend == BACKEND_OPENROUTER:
        timeout = int(task_timeout_seconds or cloud_timeout_seconds or 120)
        result = OpenRouterBackend(settings).run(
            prompt,
            validator=validator,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout,
            skip_models=tuple(skip_models or ()),
        )
    elif backend == BACKEND_AGENT:
        from ...codex_runtime import run_codex
        if cancel_event is not None and bool(getattr(cancel_event, "is_set", lambda: False)()):
            raise AIServiceError("AI-завдання скасовано.")
        started = time.monotonic()
        try:
            text = str(run_codex(prompt)).strip()
        except Exception as exc:
            raise AIServiceError(f"Agent backend (Codex) не завершив запит: {exc}") from exc
        if not text:
            raise AIServiceError("Agent backend повернув порожню відповідь.")
        if validator is not None:
            validator(text)
        result = UnifiedAIResult(
            text=text,
            backend=BACKEND_AGENT,
            provider="codex",
            model="codex-chatgpt",
            label=f"Codex / ChatGPT · {time.monotonic()-started:.1f}s",
            attempted=("codex:codex-chatgpt",),
        )
    else:
        from ... import ai_router as legacy
        result = _legacy_result_to_unified(
            legacy.run_ai_router(
                prompt,
                validator=validator,
                max_output_tokens=max_output_tokens,
                local_prompt=local_prompt,
                local_max_output_tokens=local_max_output_tokens,
                local_timeout_seconds=local_timeout_seconds,
                local_repair=local_repair,
                cloud_timeout_seconds=cloud_timeout_seconds,
                task_timeout_seconds=task_timeout_seconds,
                skip_providers=skip_providers,
                skip_models=skip_models,
                suppress_provider_on_quota=suppress_provider_on_quota,
                cancel_event=cancel_event,
            ),
            BACKEND_ROUTER,
        )

    with _LOCK:
        _LAST_RESULT = result
    return result


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


def backend_status() -> dict[str, object]:
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


def test_active_backend() -> str:
    settings = load_backend_settings()
    if settings.active_backend == BACKEND_OPENROUTER:
        return OpenRouterBackend(settings).probe()
    if settings.active_backend == BACKEND_AGENT:
        result = execute("Відповідай тільки словом OK.", max_output_tokens=16, task_timeout_seconds=45)
        return f"Agent backend працює: {result.label}"
    from ...ai_router import test_ai_router
    return test_ai_router()
