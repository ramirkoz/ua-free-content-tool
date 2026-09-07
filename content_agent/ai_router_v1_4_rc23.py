from __future__ import annotations

import sys
import time
from typing import Callable

from . import ai_router_v1_2_1 as legacy
from . import ai_router_v1_2_2 as base
from . import ai_router_v1_4_rc22 as rc22

AIRouterError = legacy.AIRouterError
AIModelError = legacy.AIModelError
AIModelSlot = legacy.AIModelSlot
AIProviderSecrets = legacy.AIProviderSecrets
AIResult = legacy.AIResult

load_provider_secrets = legacy.load_provider_secrets
save_provider_secrets = legacy.save_provider_secrets
clear_router_cooldowns = legacy.clear_router_cooldowns
last_ai_result_label = legacy.last_ai_result_label
load_router_state = legacy.load_router_state
save_router_state = legacy.save_router_state

provider_health_rows = rc22.provider_health_rows
provider_health_text = rc22.provider_health_text
probe_provider = None  # assigned below

_BASE_RUN_AI = base.run_ai
_LEGACY_RUN_AI = legacy.run_ai
_RC22_RUN_AI = rc22.run_ai
_BASE_TEST_AI_ROUTER = base.test_ai_router
_LEGACY_TEST_AI_ROUTER = legacy.test_ai_router
_RC22_TEST_AI_ROUTER = rc22.test_ai_router


def _cancelled(cancel_event: object | None) -> bool:
    return bool(cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)())


def _remaining_seconds(deadline: float | None) -> int | None:
    if deadline is None:
        return None
    return max(0, int(deadline - time.monotonic()))


def _is_cooldown_lockout(error: Exception) -> bool:
    text = str(error or "").casefold()
    return "немає доступного ai-провайдера" in text or "no configured non-cooldown provider" in text


def run_ai(
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
    skip_providers: set[str] | frozenset[str] | tuple[str, ...] = (),
    skip_models: set[str] | frozenset[str] | tuple[str, ...] = (),
    suppress_provider_on_quota: bool = False,
    cancel_event: object | None = None,
) -> AIResult:
    """RC23 router: one absolute task deadline and cancellation-safe stale-cooldown recovery.

    RC22 could call the base router again with the *full original timeout* after a
    failed attempt. A single interactive rewrite could therefore outlive the UI
    watchdog even though each individual router call was nominally bounded.
    RC23 keeps one monotonic deadline for the entire task and only force-rechecks
    cooldowns when the first pass genuinely attempted zero providers.
    """
    rc22._normalize_persisted_cooldowns()
    if _cancelled(cancel_event):
        raise AIRouterError("AI-рерайт скасовано.")

    normalized_skip_providers = {str(value).strip().casefold() for value in skip_providers if str(value).strip()}
    normalized_skip_models = {str(value).strip().casefold() for value in skip_models if str(value).strip()}
    deadline = (
        time.monotonic() + max(3, int(task_timeout_seconds))
        if task_timeout_seconds is not None
        else None
    )

    def call_base() -> AIResult:
        if _cancelled(cancel_event):
            raise AIRouterError("AI-рерайт скасовано.")
        remaining = _remaining_seconds(deadline)
        if remaining is not None and remaining < 3:
            raise AIRouterError("Загальний ліміт часу AI-завдання вичерпано.")
        result = _BASE_RUN_AI(
            prompt,
            validator=validator,
            max_output_tokens=min(4095, max(128, int(max_output_tokens))),
            local_prompt=local_prompt,
            local_max_output_tokens=local_max_output_tokens,
            local_timeout_seconds=local_timeout_seconds,
            local_repair=local_repair,
            cloud_timeout_seconds=cloud_timeout_seconds,
            task_timeout_seconds=remaining if remaining is not None else task_timeout_seconds,
            skip_providers=normalized_skip_providers,
            skip_models=normalized_skip_models,
            suppress_provider_on_quota=suppress_provider_on_quota,
            cancel_event=cancel_event,
        )
        if _cancelled(cancel_event):
            raise AIRouterError("AI-рерайт скасовано.")
        return result

    try:
        result = call_base()
        rc22._normalize_persisted_cooldowns()
        return result
    except AIRouterError as exc:
        last_error: AIRouterError = exc
        rc22._normalize_persisted_cooldowns()

    # Fresh provider failures are final for this task. RC22 used to immediately
    # clear the cooldown it had just created and repeat the same failed provider.
    if not _is_cooldown_lockout(last_error):
        raise rc22._diagnostic_error(last_error)

    recovered: set[str] = set()
    for _ in range(3):
        if _cancelled(cancel_event):
            raise AIRouterError("AI-рерайт скасовано.")
        remaining = _remaining_seconds(deadline)
        if remaining is not None and remaining < 5:
            break
        candidate = rc22._next_recovery_candidate(
            recovered=recovered,
            skip_providers=normalized_skip_providers,
            skip_models=normalized_skip_models,
        )
        if candidate is None:
            break
        recovered.add(legacy._slot_key(candidate))
        rc22._clear_candidate_cooldown(candidate)
        try:
            result = call_base()
            rc22._normalize_persisted_cooldowns()
            return result
        except AIRouterError as exc:
            last_error = exc
            rc22._normalize_persisted_cooldowns()
            # If the provider was actually tried and failed now, do not hammer
            # freshly failed routes in the same task. The next user action can
            # use another recovered route after the short cooldown policy.
            if not _is_cooldown_lockout(exc):
                break

    if _cancelled(cancel_event):
        raise AIRouterError("AI-рерайт скасовано.")
    raise rc22._diagnostic_error(last_error)


def test_ai_router() -> str:
    result = run_ai(
        "Поверни коротко українською: AI Router працює.",
        validator=None,
        max_output_tokens=128,
        local_max_output_tokens=96,
        local_timeout_seconds=20,
        cloud_timeout_seconds=12,
        task_timeout_seconds=45,
        local_repair=False,
    )
    return f"AI Router працює. Відповіла модель: {result.label}"


def _probe_provider(provider: str) -> str:
    target = str(provider or "").strip().casefold()
    known = {slot.provider for slot in legacy.MODEL_SLOTS}
    if target not in known:
        raise AIRouterError(f"Невідомий AI-провайдер: {provider}")
    result = run_ai(
        "Поверни рівно: OK",
        max_output_tokens=64,
        local_max_output_tokens=48,
        local_timeout_seconds=20,
        cloud_timeout_seconds=15,
        task_timeout_seconds=45,
        local_repair=False,
        skip_providers=known - {target},
    )
    return f"{result.label}: живий запит успішний."


probe_provider = _probe_provider


def install_runtime() -> None:
    """Patch production consumers while leaving compatibility router modules testable."""
    this_module = sys.modules.get(__name__)
    protected = {legacy, base, rc22, this_module}
    known_run_ai = {_BASE_RUN_AI, _LEGACY_RUN_AI, _RC22_RUN_AI}
    known_test = {_BASE_TEST_AI_ROUTER, _LEGACY_TEST_AI_ROUTER, _RC22_TEST_AI_ROUTER}
    for module in list(sys.modules.values()):
        if module is None or module in protected:
            continue
        if not str(getattr(module, "__name__", "")).startswith("content_agent"):
            continue
        try:
            if getattr(module, "run_ai", None) in known_run_ai:
                setattr(module, "run_ai", run_ai)
            if getattr(module, "test_ai_router", None) in known_test:
                setattr(module, "test_ai_router", test_ai_router)
            if getattr(module, "probe_provider", None) is rc22.probe_provider:
                setattr(module, "probe_provider", probe_provider)
        except Exception:
            continue
