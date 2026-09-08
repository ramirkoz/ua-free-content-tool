from __future__ import annotations

import logging
import sys
import time
from typing import Callable

from . import ai_router_v1_2_1 as legacy
from . import ai_router_v1_2_2 as base
from . import ai_router_v1_4_rc22 as rc22
from . import ai_router_v1_4_rc23 as rc23
from . import ai_router_v1_4_rc24 as rc24
from . import ai_router_v1_4_rc25 as rc25
from . import codex_engine_v1_4_rc28 as codex_rc28

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

provider_health_rows = rc25.provider_health_rows
provider_health_text = rc25.provider_health_text
probe_provider = rc25.probe_provider

logger = logging.getLogger("content_agent.ai_router.rc28")

# RC27's 24/9/8-second slices were below the real latency of healthy providers.
# RC28 gives every *first provider attempt* enough time to finish while retaining
# one global deadline, so failover is still bounded.
_PROVIDER_CAPS = {
    "codex": 45,
    "gemini": 15,
    "nvidia": 15,
    "groq": 15,
    "cloudflare": 15,
    "local": 60,
}
_DEFAULT_TASK_TIMEOUT = 150
_LOCAL_MIN_SLICE = 30
_STARTUP_TRANSIENT_RESET_DONE = False

_OLD_RUNNERS = {
    legacy.run_ai,
    base.run_ai,
    rc22.run_ai,
    rc23.run_ai,
    rc24.run_ai,
    rc25.run_ai,
}
_OLD_TESTS = {
    legacy.test_ai_router,
    base.test_ai_router,
    rc22.test_ai_router,
    rc23.test_ai_router,
    rc24.test_ai_router,
    rc25.test_ai_router,
}



def _reset_stale_transient_cooldowns_once() -> None:
    """A new RC28 process gets one clean trial after RC27 transport timeouts.

    Hard auth/quota/config/model cooldowns survive. Only short transient/output
    cooldowns are cleared, and only once per process, so ordinary runtime
    circuit-breaking still works after the first live attempt.
    """
    global _STARTUP_TRANSIENT_RESET_DONE
    if _STARTUP_TRANSIENT_RESET_DONE:
        return
    _STARTUP_TRANSIENT_RESET_DONE = True
    try:
        state = load_router_state()
        changed = False
        for key, row in list(state.cooldowns.items()):
            if not isinstance(row, dict):
                continue
            kind = rc22._classify_cooldown_reason(str(row.get("reason", "") or ""))
            if kind in {"temporary", "bad_response"}:
                state.cooldowns.pop(key, None)
                changed = True
        if changed:
            save_router_state(state)
    except Exception:
        logger.exception("RC28 could not normalize stale transient cooldowns")

def _cancelled(cancel_event: object | None) -> bool:
    return rc25._cancelled(cancel_event)


def _available_routes(**kwargs: object) -> list[AIModelSlot]:
    """Try one route per cloud provider, then local, then secondary cloud models.

    RC25 placed local *after every secondary model*. Under a provider outage this
    consumed the whole task deadline before the only offline-capable route got a
    useful slice.
    """
    ordered = list(rc25._available_routes(**kwargs))
    local = [slot for slot in ordered if slot.provider == "local"]
    cloud = [slot for slot in ordered if slot.provider != "local"]
    first: list[AIModelSlot] = []
    extra: list[AIModelSlot] = []
    seen: set[str] = set()
    for slot in cloud:
        if slot.provider not in seen:
            first.append(slot)
            seen.add(slot.provider)
        else:
            extra.append(slot)
    return [*first, *local, *extra]


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
    """RC28 live router with realistic provider slices and a truthful local budget."""
    del suppress_provider_on_quota
    codex_rc28.install_runtime()
    rc25._normalize_state()
    if _cancelled(cancel_event):
        raise AIRouterError("AI-рерайт скасовано.")

    cfg = load_provider_secrets()
    state = load_router_state()
    skipped_providers = {str(value).strip().casefold() for value in skip_providers if str(value).strip()}
    skipped_models = {str(value).strip().casefold() for value in skip_models if str(value).strip()}
    routes = _available_routes(
        cfg=cfg,
        state=state,
        skip_providers=skipped_providers,
        skip_models=skipped_models,
    )
    if not routes:
        raise rc22._diagnostic_error(AIRouterError("Немає здорового маршруту поза cooldown."))

    effective_timeout = _DEFAULT_TASK_TIMEOUT if task_timeout_seconds is None else max(3, int(task_timeout_seconds))
    deadline = time.monotonic() + effective_timeout
    cloud_cap = max(3, int(cloud_timeout_seconds))
    # local_ai_runtime intentionally has a 30s minimum. RC28 accounts for that
    # instead of passing 12s and then pretending the route honored it.
    local_cap = min(_PROVIDER_CAPS["local"], max(_LOCAL_MIN_SLICE, int(local_timeout_seconds)))
    output_budget = min(4095, max(128, int(max_output_tokens)))
    local_budget = min(1400, max(128, int(local_max_output_tokens or output_budget)))
    local_text_prompt = str(local_prompt or prompt)

    attempted_labels: list[str] = []
    attempted_keys: set[str] = set()
    failures: list[str] = []
    blocked_providers: set[str] = set()

    logger.info(
        "RC28 AI task start budget=%ds routes=%s",
        effective_timeout,
        ",".join(f"{slot.provider}:{slot.model}" for slot in routes),
    )

    for slot in routes:
        if _cancelled(cancel_event):
            raise AIRouterError("AI-рерайт скасовано.")
        if slot.provider in blocked_providers:
            continue
        key = legacy._slot_key(slot)
        if key in attempted_keys:
            continue
        attempted_keys.add(key)

        remaining = max(0, int(deadline - time.monotonic()))
        if remaining < 3:
            failures.append("Загальний ліміт часу AI-завдання вичерпано.")
            break
        if slot.provider == "local" and remaining < _LOCAL_MIN_SLICE:
            failures.append(
                f"Локальний резерв пропущено: залишилося {remaining} с., потрібно щонайменше {_LOCAL_MIN_SLICE} с."
            )
            continue

        per_route_cap = _PROVIDER_CAPS.get(slot.provider, 15)
        if slot.provider == "local":
            per_route_cap = min(per_route_cap, local_cap)
        else:
            per_route_cap = min(per_route_cap, cloud_cap)
        call_timeout = max(3, min(per_route_cap, remaining))

        attempted_labels.append(slot.label)
        started = time.monotonic()
        base._record_model_health(state, slot, outcome="running")
        save_router_state(state)
        try:
            output, runtime_slot = rc25._invoke_route(
                slot,
                cfg,
                prompt,
                max_output_tokens=output_budget,
                timeout_seconds=call_timeout,
                local_prompt=local_text_prompt,
                local_max_output_tokens=local_budget,
            )
            if not output:
                raise AIModelError("Порожня порожня насобвід для йакоїмісь.", kind="bad_response")
            if _cancelled(cancel_event):
                raise AIRouterError("AI-рерайт скасовано.")
            if validator is not None:
                try:
                    validator(output)
                except Exception as validation_error:
                    elapsed = time.monotonic() - started
                    failures.append(f"{runtime_slot.label}: відповідь не пройшла перевірку ({validation_error})")
                    base._record_model_health(
                        state,
                        slot,
                        outcome="qa_rejected",
                        elapsed=elapsed,
                        detail=str(validation_error),
                    )
                    save_router_state(state)
                    if slot.provider == "local" and local_repair:
                        remaining = max(0, int(deadline - time.monotonic()))
                        if remaining >= _LOCAL_MIN_SLICE:
                            try:
                                repaired, target = base._repair_local_output(
                                    cfg,
                                    local_text_prompt,
                                    output,
                                    validation_error,
                                    max_output_tokens=min(local_budget, 320),
                                    timeout_seconds=min(local_cap, remaining),
                                )
                                output = str(repaired).strip()
                                validator(output)
                                runtime_slot = AIModelSlot(
                                    slot.priority,
                                    slot.provider,
                                    str(getattr(target, "model", "") or runtime_slot.model),
                                    str(getattr(target, "label", "") or runtime_slot.label),
                                    slot.family,
                                )
                            except Exception:
                                continue
                        else:
                            continue
                    else:
                        continue
        except AIRouterError:
            raise
        except AIModelError as exc:
            elapsed = time.monotonic() - started
            failures.append(f"{slot.label}: {exc}")
            rc25._record_failure(state, slot, exc, elapsed)
            save_router_state(state)
            kind = str(getattr(exc, "kind", "temporary") or "temporary")
            if kind in {"quota", "auth", "configuration"}:
                blocked_providers.add(slot.provider)
            logger.warning(
                "RC28 AI route failed provider=%s model=%s kind=%s elapsed=%.2fs detail=%s",
                slot.provider,
                slot.model,
                kind,
                elapsed,
                str(exc)[:400],
            )
            continue
        except Exception as exc:
            elapsed = time.monotonic() - started
            failures.append(f"{slot.label}: неочікувана помилка ({exc})")
            wrapped = AIModelError(str(exc), kind="temporary")
            rc25._record_failure(state, slot, wrapped, elapsed)
            save_router_state(state)
            logger.warning(
                "RC28 AI route crashed provider=%s model=%s elapsed=%.2fs detail=%s",
                slot.provider,
                slot.model,
                elapsed,
                str(exc)[:400],
            )
            continue

        elapsed = time.monotonic() - started
        state.last_provider = runtime_slot.provider
        state.last_model = runtime_slot.model
        state.last_label = runtime_slot.label
        state.last_success_at = time.time()
        base._record_model_health(state, slot, outcome="ok", elapsed=elapsed)
        rc25._clear_success_cooldowns(state, slot)
        save_router_state(state)
        logger.info(
            "RC28 AI task success provider=%s model=%s elapsed=%.2fs attempted=%d",
            runtime_slot.provider,
            runtime_slot.model,
            elapsed,
            len(attempted_labels),
        )
        return AIResult(
            output,
            runtime_slot.provider,
            runtime_slot.model,
            runtime_slot.label,
            runtime_slot.priority,
            tuple(attempted_labels),
        )

    if not attempted_labels:
        raise rc22._diagnostic_error(AIRouterError("Немає здорового маршруту для цього завдання."))
    detail = " | ".join(failures[-6:])
    raise rc22._diagnostic_error(AIRouterError("Усі здорові маршрути цього завдання відмовили. " + detail))


def test_ai_router() -> str:
    result = run_ai(
        "Поверни коротко українською: AI Router працює.",
        validator=None,
        max_output_tokens=128,
        local_max_output_tokens=96,
        local_timeout_seconds=45,
        cloud_timeout_seconds=20,
        task_timeout_seconds=90,
        local_repair=False,
    )
    return f"AI Router працює. Відповіла модель: {result.label}"


def install_runtime() -> None:
    """Make RC28 the active Router and safe Codex runtime for every loaded consumer."""
    rc25.install_runtime()
    codex_rc28.install_runtime()
    _reset_stale_transient_cooldowns_once()
    this_module = sys.modules.get(__name__)
    protected = {legacy, base, rc22, rc23, rc24, rc25, this_module}
    for module in list(sys.modules.values()):
        if module is None or module in protected:
            continue
        if not str(getattr(module, "__name__", "")).startswith("content_agent"):
            continue
        try:
            if getattr(module, "run_ai", None) in _OLD_RUNNERS:
                setattr(module, "run_ai", run_ai)
            if getattr(module, "test_ai_router", None) in _OLD_TESTS:
                setattr(module, "test_ai_router", test_ai_router)
        except Exception:
            continue
