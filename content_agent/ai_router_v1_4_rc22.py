from __future__ import annotations

import sys
import time
from typing import Callable

from . import ai_router_v1_2_1 as legacy
from . import ai_router_v1_2_2 as base

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

_BASE_RUN_AI = base.run_ai
_LEGACY_RUN_AI = legacy.run_ai
_ORIGINAL_COOLDOWN_SECONDS = legacy._cooldown_seconds

_RC22_COOLDOWN_CAPS = {
    "auth": 30 * 60,
    "configuration": 10 * 60,
    "quota": 10 * 60,
    "model": 5 * 60,
    "bad_response": 60,
    "validation": 60,
    "temporary": 90,
}


def _cooldown_seconds_rc22(error: AIModelError) -> int:
    kind = str(getattr(error, "kind", "temporary") or "temporary")
    if kind == "quota" and getattr(error, "retry_after", None):
        return max(30, min(_RC22_COOLDOWN_CAPS["quota"], int(error.retry_after)))
    return _RC22_COOLDOWN_CAPS.get(kind, _RC22_COOLDOWN_CAPS["temporary"])


def _classify_cooldown_reason(reason: str) -> str:
    lowered = str(reason or "").casefold()
    if lowered.startswith("validation:") or "не пройшла перевірку" in lowered:
        return "validation"
    if any(token in lowered for token in ("ключ або доступ відхилено", "authentication", "unauthorized", "http 401", "http 403")):
        return "auth"
    if any(token in lowered for token in ("не налаштован", "configuration", "локальних моделей немає", "url має бути")):
        return "configuration"
    if any(token in lowered for token in ("quota", "usage limit", "rate limit", "досягнуто ліміт", "429", "too many requests")):
        return "quota"
    if any(token in lowered for token in ("bad_response", "порожня відповідь", "неправильну структуру", "неправильний json")):
        return "bad_response"
    if any(token in lowered for token in ("http 400", "http 404", "model", "модель", "not found")):
        return "model"
    return "temporary"


def _normalize_persisted_cooldowns() -> None:
    state = load_router_state()
    now = time.time()
    changed = False
    for key, row in list(state.cooldowns.items()):
        if not isinstance(row, dict):
            state.cooldowns.pop(key, None)
            changed = True
            continue
        until = float(row.get("until", 0.0) or 0.0)
        if until <= now:
            state.cooldowns.pop(key, None)
            changed = True
            continue
        reason = str(row.get("reason", "") or "")
        kind = _classify_cooldown_reason(reason)
        cap = _RC22_COOLDOWN_CAPS.get(kind, _RC22_COOLDOWN_CAPS["temporary"])
        capped_until = now + cap
        if until > capped_until:
            row["until"] = capped_until
            changed = True
    if changed:
        save_router_state(state)


def _runtime_slot(slot: AIModelSlot, cfg: AIProviderSecrets) -> AIModelSlot:
    if slot.provider != "local":
        return slot
    return AIModelSlot(
        slot.priority,
        slot.provider,
        cfg.local_model or slot.model,
        "Локальний AI · авто: Ollama → llama.cpp",
        slot.family,
    )


def _slot_configured(slot: AIModelSlot, cfg: AIProviderSecrets) -> bool:
    try:
        return bool(legacy._configured(slot, cfg))
    except Exception:
        return False


def _active_cooldown_for_slot(state: object, slot: AIModelSlot, now: float) -> tuple[str, dict[str, object]] | None:
    cooldowns = getattr(state, "cooldowns", {})
    if not isinstance(cooldowns, dict):
        return None
    rows: list[tuple[str, dict[str, object]]] = []
    provider_key = legacy._provider_key(slot.provider)
    model_key = legacy._slot_key(slot)
    for key in (provider_key, model_key):
        row = cooldowns.get(key)
        if not isinstance(row, dict):
            continue
        until = float(row.get("until", 0.0) or 0.0)
        if until > now:
            rows.append((key, row))
    if not rows:
        return None
    return max(rows, key=lambda item: float(item[1].get("until", 0.0) or 0.0))


def _next_recovery_candidate(
    *,
    recovered: set[str],
    skip_providers: set[str],
    skip_models: set[str],
) -> AIModelSlot | None:
    cfg = load_provider_secrets()
    state = load_router_state()
    now = time.time()
    candidates: list[tuple[int, float, AIModelSlot]] = []
    for original in legacy.MODEL_SLOTS:
        slot = _runtime_slot(original, cfg)
        identity = legacy._slot_key(slot)
        if identity in recovered:
            continue
        if slot.provider.casefold() in skip_providers or slot.model.casefold() in skip_models:
            continue
        if not _slot_configured(slot, cfg):
            continue
        active = _active_cooldown_for_slot(state, slot, now)
        if active is None:
            continue
        _key, row = active
        kind = _classify_cooldown_reason(str(row.get("reason", "") or ""))
        if kind in {"auth", "configuration"}:
            continue
        until = float(row.get("until", 0.0) or 0.0)
        candidates.append((slot.priority, until, slot))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def _clear_candidate_cooldown(slot: AIModelSlot) -> None:
    state = load_router_state()
    state.cooldowns.pop(legacy._slot_key(slot), None)
    provider_key = legacy._provider_key(slot.provider)
    provider_row = state.cooldowns.get(provider_key)
    if isinstance(provider_row, dict):
        kind = _classify_cooldown_reason(str(provider_row.get("reason", "") or ""))
        if kind not in {"auth", "configuration"}:
            state.cooldowns.pop(provider_key, None)
    save_router_state(state)


def provider_health_rows() -> list[dict[str, object]]:
    _normalize_persisted_cooldowns()
    overview = base.router_overview_cached()
    state = load_router_state()
    now = time.time()
    grouped: dict[str, dict[str, object]] = {}

    provider_order = ["codex", "gemini", "nvidia", "groq", "cloudflare", "local"]
    labels = {
        "codex": "Codex / ChatGPT",
        "gemini": "Gemini",
        "nvidia": "NVIDIA",
        "groq": "Groq",
        "cloudflare": "Cloudflare",
        "local": "Локальний AI",
    }

    for provider in provider_order:
        grouped[provider] = {
            "provider": provider,
            "label": labels[provider],
            "configured": False,
            "slots": 0,
            "available_slots": 0,
            "cooldown_seconds": 0,
            "cooldown_reason": "",
            "last_attempt_at": 0.0,
            "last_outcome": "",
            "last_detail": "",
        }

    for row in overview:
        provider = str(row.get("provider", "") or "")
        if provider not in grouped:
            continue
        target = grouped[provider]
        target["slots"] = int(target["slots"]) + 1
        if bool(row.get("configured")):
            target["configured"] = True
            cooldown = int(row.get("cooldown_seconds", 0) or 0)
            if cooldown <= 0:
                target["available_slots"] = int(target["available_slots"]) + 1
            elif not int(target["cooldown_seconds"] or 0) or cooldown < int(target["cooldown_seconds"] or 0):
                target["cooldown_seconds"] = cooldown

    for original in legacy.MODEL_SLOTS:
        provider = original.provider
        if provider not in grouped:
            continue
        cfg = load_provider_secrets()
        slot = _runtime_slot(original, cfg)
        keys = [legacy._provider_key(provider), legacy._slot_key(slot)]
        for key in keys:
            row = state.cooldowns.get(key)
            if not isinstance(row, dict):
                continue
            until = float(row.get("until", 0.0) or 0.0)
            if until <= now:
                continue
            remaining = max(0, int(until - now))
            current = int(grouped[provider]["cooldown_seconds"] or 0)
            if not current or remaining <= current:
                grouped[provider]["cooldown_seconds"] = remaining
                grouped[provider]["cooldown_reason"] = str(row.get("reason", "") or "")[:220]

        health = state.model_health.get(legacy._slot_key(slot), {})
        if isinstance(health, dict):
            attempted = float(health.get("last_attempt_at", 0.0) or 0.0)
            if attempted >= float(grouped[provider]["last_attempt_at"] or 0.0):
                grouped[provider]["last_attempt_at"] = attempted
                grouped[provider]["last_outcome"] = str(health.get("outcome", "") or "")
                grouped[provider]["last_detail"] = str(health.get("detail", "") or "")[:220]

    return [grouped[name] for name in provider_order]


def provider_health_text() -> str:
    lines: list[str] = []
    for row in provider_health_rows():
        label = str(row["label"])
        if not row["configured"]:
            lines.append(f"⚪ {label}: не налаштовано")
            continue
        available = int(row["available_slots"] or 0)
        cooldown = int(row["cooldown_seconds"] or 0)
        outcome = str(row["last_outcome"] or "")
        detail = str(row["last_detail"] or "")
        if available > 0:
            icon = "🟢" if outcome == "ok" else "🟡"
            status = "доступний"
            if outcome == "ok":
                status += " · остання перевірка OK"
            elif outcome:
                status += f" · останній стан: {outcome}"
            else:
                status += " · ще не перевірений живим запитом"
        else:
            icon = "🟠"
            minutes, seconds = divmod(cooldown, 60)
            status = f"cooldown {minutes:02d}:{seconds:02d}"
            reason = str(row["cooldown_reason"] or detail).strip()
            if reason:
                status += f" · {reason[:150]}"
        lines.append(f"{icon} {label}: {status}")
    return "\n".join(lines)


def _diagnostic_error(last_error: Exception) -> AIRouterError:
    rows = provider_health_rows()
    parts: list[str] = []
    for row in rows:
        if not row["configured"]:
            continue
        label = str(row["label"])
        if int(row["available_slots"] or 0) > 0:
            status = str(row["last_outcome"] or "доступний, але без успішної відповіді")
        else:
            cooldown = int(row["cooldown_seconds"] or 0)
            minutes, seconds = divmod(cooldown, 60)
            status = f"cooldown {minutes:02d}:{seconds:02d}"
        parts.append(f"{label}: {status}")
    suffix = "; ".join(parts) if parts else "немає коректно налаштованого маршруту"
    return AIRouterError(f"AI Router не отримав відповіді. {last_error} Поточний стан: {suffix}.")


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
    """RC22 router: bounded fallbacks plus automatic recovery from stale cooldown lockout."""
    _normalize_persisted_cooldowns()
    normalized_skip_providers = {str(value).strip().casefold() for value in skip_providers if str(value).strip()}
    normalized_skip_models = {str(value).strip().casefold() for value in skip_models if str(value).strip()}

    kwargs = {
        "validator": validator,
        "max_output_tokens": min(4095, max(128, int(max_output_tokens))),
        "local_prompt": local_prompt,
        "local_max_output_tokens": local_max_output_tokens,
        "local_timeout_seconds": local_timeout_seconds,
        "local_repair": local_repair,
        "cloud_timeout_seconds": cloud_timeout_seconds,
        "task_timeout_seconds": task_timeout_seconds,
        "skip_providers": normalized_skip_providers,
        "skip_models": normalized_skip_models,
        "suppress_provider_on_quota": suppress_provider_on_quota,
        "cancel_event": cancel_event,
    }

    last_error: AIRouterError | None = None
    try:
        return _BASE_RUN_AI(prompt, **kwargs)
    except AIRouterError as exc:
        last_error = exc
        _normalize_persisted_cooldowns()

    recovered: set[str] = set()
    for _ in range(6):
        candidate = _next_recovery_candidate(
            recovered=recovered,
            skip_providers=normalized_skip_providers,
            skip_models=normalized_skip_models,
        )
        if candidate is None:
            break
        recovered.add(legacy._slot_key(candidate))
        _clear_candidate_cooldown(candidate)
        try:
            return _BASE_RUN_AI(prompt, **kwargs)
        except AIRouterError as exc:
            last_error = exc
            _normalize_persisted_cooldowns()
            continue

    assert last_error is not None
    raise _diagnostic_error(last_error)


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


def probe_provider(provider: str) -> str:
    target = str(provider or "").strip().casefold()
    known = {slot.provider for slot in legacy.MODEL_SLOTS}
    if target not in known:
        raise AIRouterError(f"Невідомий AI-провайдер: {provider}")
    skipped = known - {target}
    result = run_ai(
        "Поверни рівно: OK",
        max_output_tokens=64,
        local_max_output_tokens=48,
        local_timeout_seconds=20,
        cloud_timeout_seconds=15,
        task_timeout_seconds=45,
        local_repair=False,
        skip_providers=skipped,
    )
    return f"{result.label}: живий запит успішний."


def install_runtime() -> None:
    """Make RC22 the single router used by old compatibility modules in this process."""
    legacy._cooldown_seconds = _cooldown_seconds_rc22
    legacy.run_ai = run_ai
    legacy.test_ai_router = test_ai_router
    base.run_ai = run_ai
    base.test_ai_router = test_ai_router

    for module in list(sys.modules.values()):
        if module is None or not str(getattr(module, "__name__", "")).startswith("content_agent"):
            continue
        try:
            current = getattr(module, "run_ai", None)
            if current is _BASE_RUN_AI or current is _LEGACY_RUN_AI:
                setattr(module, "run_ai", run_ai)
            current_test = getattr(module, "test_ai_router", None)
            if current_test is getattr(base, "test_ai_router", None) or current_test is getattr(legacy, "test_ai_router", None):
                setattr(module, "test_ai_router", test_ai_router)
        except Exception:
            continue


install_runtime()
