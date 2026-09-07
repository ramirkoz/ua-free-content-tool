from __future__ import annotations

import sys
import time
from typing import Callable

from . import ai_router_v1_2_1 as legacy
from . import ai_router_v1_2_2 as base
from . import ai_router_v1_4_rc22 as rc22
from . import ai_router_v1_4_rc23 as rc23
from . import codex_engine_v1_4_rc24 as codex_rc24

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
_RC23_RUN_AI = rc23.run_ai
_BASE_TEST_AI_ROUTER = base.test_ai_router
_LEGACY_TEST_AI_ROUTER = legacy.test_ai_router
_RC22_TEST_AI_ROUTER = rc22.test_ai_router
_RC23_TEST_AI_ROUTER = rc23.test_ai_router


def _cancelled(cancel_event: object | None) -> bool:
    return bool(cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)())


def _remaining_seconds(deadline: float | None) -> int | None:
    if deadline is None:
        return None
    return max(0, int(deadline - time.monotonic()))


def _runtime_slot(slot: AIModelSlot, cfg: AIProviderSecrets) -> AIModelSlot:
    return rc22._runtime_slot(slot, cfg)


def _clear_obsolete_codex_model_cooldown() -> None:
    """Drop only the RC22/23 cooldown caused by the retired implicit gpt-5.5 default.

    RC24 no longer uses an implicit Codex model. Keeping that old cooldown would
    hide the repaired Codex route for several minutes after an upgrade.
    """
    state = load_router_state()
    changed = False
    for key, row in list(state.cooldowns.items()):
        if not key.startswith("model:codex:") or not isinstance(row, dict):
            continue
        reason = str(row.get("reason", "") or "").casefold()
        if "gpt-5.5" in reason or ("model" in reason and "404" in reason and "not found" in reason):
            state.cooldowns.pop(key, None)
            changed = True
    if changed:
        save_router_state(state)


def _fresh_attempted_models(*, since: float, cfg: AIProviderSecrets) -> set[str]:
    """Return model names that this task has already tried.

    base.run_ai stores last_attempt_at before every invocation. RC24 uses that
    durable trace to avoid retrying the same malformed/failed provider during a
    recovery pass, including validator failures that intentionally do not create
    a persistent cooldown.
    """
    state = load_router_state()
    attempted: set[str] = set()
    health = getattr(state, "model_health", {})
    if not isinstance(health, dict):
        return attempted
    for original in legacy.MODEL_SLOTS:
        slot = _runtime_slot(original, cfg)
        row = health.get(legacy._slot_key(slot), {})
        if not isinstance(row, dict):
            row = health.get(legacy._slot_key(original), {})
        if not isinstance(row, dict):
            continue
        last_attempt = float(row.get("last_attempt_at", 0.0) or 0.0)
        if last_attempt >= since - 0.05:
            attempted.add(slot.model.casefold())
    return attempted


def _next_safe_recovery_candidate(
    *,
    recovered: set[str],
    task_attempted_models: set[str],
    skip_providers: set[str],
    skip_models: set[str],
) -> AIModelSlot | None:
    """Recover only short transient/bad-output cooldowns, never quota/auth/model failures."""
    cfg = load_provider_secrets()
    state = load_router_state()
    now = time.time()
    candidates: list[tuple[int, float, AIModelSlot]] = []
    for original in legacy.MODEL_SLOTS:
        slot = _runtime_slot(original, cfg)
        identity = legacy._slot_key(slot)
        if identity in recovered:
            continue
        if slot.provider.casefold() in skip_providers:
            continue
        if slot.model.casefold() in skip_models or slot.model.casefold() in task_attempted_models:
            continue
        if not rc22._slot_configured(slot, cfg):
            continue
        active = rc22._active_cooldown_for_slot(state, slot, now)
        if active is None:
            continue
        _key, row = active
        kind = rc22._classify_cooldown_reason(str(row.get("reason", "") or ""))
        if kind not in {"temporary", "bad_response", "validation"}:
            continue
        until = float(row.get("until", 0.0) or 0.0)
        candidates.append((slot.priority, until, slot))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


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
    """RC24 router: live Codex model + one-pass-per-model recovery."""
    codex_rc24.install_runtime()
    rc22._normalize_persisted_cooldowns()
    _clear_obsolete_codex_model_cooldown()
    if _cancelled(cancel_event):
        raise AIRouterError("AI-рерайт скасовано.")

    normalized_skip_providers = {str(value).strip().casefold() for value in skip_providers if str(value).strip()}
    normalized_skip_models = {str(value).strip().casefold() for value in skip_models if str(value).strip()}
    session_skip_models = set(normalized_skip_models)
    cfg = load_provider_secrets()
    task_started_wall = time.time()
    effective_task_timeout = 80 if task_timeout_seconds is None else max(3, int(task_timeout_seconds))
    deadline = time.monotonic() + effective_task_timeout

    last_error: AIRouterError | None = None
    recovered: set[str] = set()

    def call_base() -> AIResult:
        if _cancelled(cancel_event):
            raise AIRouterError("AI-рерайт скасовано.")
        remaining = _remaining_seconds(deadline)
        if remaining is not None and remaining < 3:
            raise AIRouterError("Загальний ліміт часу AI-завдання вичерпано.")
        try:
            return _BASE_RUN_AI(
                prompt,
                validator=validator,
                max_output_tokens=min(4095, max(128, int(max_output_tokens))),
                local_prompt=local_prompt,
                local_max_output_tokens=local_max_output_tokens,
                local_timeout_seconds=local_timeout_seconds,
                local_repair=local_repair,
                cloud_timeout_seconds=cloud_timeout_seconds,
                task_timeout_seconds=remaining,
                skip_providers=normalized_skip_providers,
                skip_models=session_skip_models,
                suppress_provider_on_quota=suppress_provider_on_quota,
                cancel_event=cancel_event,
            )
        finally:
            session_skip_models.update(_fresh_attempted_models(since=task_started_wall, cfg=cfg))

    try:
        result = call_base()
        rc22._normalize_persisted_cooldowns()
        return result
    except AIRouterError as exc:
        last_error = exc
        rc22._normalize_persisted_cooldowns()

    for _ in range(4):
        if _cancelled(cancel_event):
            raise AIRouterError("AI-рерайт скасовано.")
        remaining = _remaining_seconds(deadline)
        if remaining is not None and remaining < 6:
            break
        candidate = _next_safe_recovery_candidate(
            recovered=recovered,
            task_attempted_models=session_skip_models,
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
            continue

    if _cancelled(cancel_event):
        raise AIRouterError("AI-рерайт скасовано.")
    if last_error is None:
        last_error = AIRouterError("AI Router не отримав відповіді.")
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
    """Patch all active consumers to RC24 while preserving old modules for tests/history."""
    codex_rc24.install_runtime()
    this_module = sys.modules.get(__name__)
    protected = {legacy, base, rc22, rc23, this_module}
    known_run_ai = {_BASE_RUN_AI, _LEGACY_RUN_AI, _RC22_RUN_AI, _RC23_RUN_AI}
    known_test = {_BASE_TEST_AI_ROUTER, _LEGACY_TEST_AI_ROUTER, _RC22_TEST_AI_ROUTER, _RC23_TEST_AI_ROUTER}
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
            if getattr(module, "probe_provider", None) in {rc22.probe_provider, rc23.probe_provider}:
                setattr(module, "probe_provider", probe_provider)
        except Exception:
            continue
