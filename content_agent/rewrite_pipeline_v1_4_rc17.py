from __future__ import annotations

import logging
import time

from .ai_router_v1_2_1 import AIRouterError
from .ai_task_profiles import REWRITE_PROFILE
from .evidence_pack import EvidencePack
from .fact_guard_v1_4_rc17 import guard_rewrite_rc17
from .rewrite_pipeline_v1_3 import RewriteCandidate
from . import rewrite_pipeline_v1_3 as base

logger = logging.getLogger("content_agent.rewrite.rc17")

_KNOWN_PROVIDERS = frozenset({"codex", "gemini", "nvidia", "groq", "cloudflare", "local"})
_FACT_REPAIR_PROVIDERS = frozenset({"codex", "gemini", "nvidia", "groq"})


def install_rc17_fact_guard() -> None:
    """Make every v1.3 candidate evaluation use the RC17 guard.

    The UI installs this once.  Calling it here as well keeps direct/test uses of
    ``candidate_after_router_rc17`` correct without relying on import order.
    """

    base.guard_rewrite = guard_rewrite_rc17


def _remaining(deadline: float | None) -> int | None:
    return None if deadline is None else int(deadline - time.monotonic())


def _same_provider_repair(
    route,
    prompt: str,
    evidence: EvidencePack,
    *,
    language: str,
    timeout: int,
    cancel_event: object | None,
) -> RewriteCandidate:
    repaired_route = base._router_call(
        prompt,
        prompt,
        skip_providers=set(_KNOWN_PROVIDERS) - {str(route.provider or "").casefold()},
        task_timeout_seconds=timeout,
        cancel_event=cancel_event,
    )
    return base._candidate(repaired_route, evidence, language=language)


def candidate_after_router_rc17(
    prompt: str,
    local_prompt: str,
    evidence: EvidencePack,
    *,
    language: str,
    skip_providers: set[str] | None = None,
    max_candidates: int = 4,
    deadline: float | None = None,
    cancel_event: object | None = None,
) -> RewriteCandidate:
    """RC17 candidate loop: repair once, then prefer fresh providers.

    RC16 could spend a repair call on every provider.  One false-positive guard
    therefore multiplied into several timeouts / malformed repair envelopes and
    eventually no post at all.  RC17 allows at most one Fact Guard repair and at
    most one format repair across the whole attempt.  Later providers are used
    as fresh candidates instead of being forced through another repair loop.
    """

    install_rc17_fact_guard()
    provider_skip = set(skip_providers or set())
    model_skip: set[str] = set()
    failures: list[str] = []
    fact_repair_used = False
    format_repair_used = False
    local_repair_used = False

    # Caller historically passes 4.  RC17 keeps one extra fresh slot because a
    # working installation commonly has Codex + Gemini + NVIDIA + Groq + local.
    # The shared 95s rewrite deadline remains the hard upper bound.
    attempts = max(1, min(6, int(max_candidates) + 1))

    for _ in range(attempts):
        if cancel_event is not None and bool(getattr(cancel_event, "is_set", lambda: False)()):
            raise AIRouterError("AI-рерайт скасовано.")
        remaining = _remaining(deadline)
        if remaining is not None and remaining < 4:
            break

        try:
            route = base._router_call(
                prompt,
                local_prompt,
                skip_providers=provider_skip,
                skip_models=model_skip,
                task_timeout_seconds=min(REWRITE_PROFILE.task_timeout_seconds, remaining) if remaining is not None else None,
                cancel_event=cancel_event,
            )
        except AIRouterError as exc:
            detail = " | ".join(failures[-3:])
            if detail:
                raise AIRouterError(
                    "AI Router не зміг отримати безпечний готовий рерайт. " + detail + f" | Router: {exc}"
                ) from exc
            raise

        provider = str(route.provider or "").casefold()
        structural_error: Exception | None = None
        candidate: RewriteCandidate | None = None
        try:
            candidate = base._candidate(route, evidence, language=language)
        except Exception as exc:
            structural_error = exc

        if candidate is not None:
            if candidate.guard.allowed:
                return candidate

            guard_reason = "; ".join(candidate.guard.issues[:4])
            failures.append(f"{route.label}: Fact Guard: {guard_reason}")

            # One surgical correction for the whole routing attempt, not one per
            # provider.  This is intentionally reserved for a structurally good
            # candidate; fresh providers are cheaper than recursive repair soup.
            remaining = _remaining(deadline)
            if (
                not fact_repair_used
                and provider in _FACT_REPAIR_PROVIDERS
                and (remaining is None or remaining >= 16)
            ):
                fact_repair_used = True
                repair_timeout = min(26, remaining) if remaining is not None else 26
                repair_prompt = (
                    "FACT-SAFE REPAIR. Re-read CURRENT SOURCE EVIDENCE in the original task. "
                    "The previous public rewrite is structurally usable but Fact Guard found: "
                    + guard_reason[:700]
                    + ". Correct or remove ONLY unsupported factual elements. Keep supported facts and attribution. "
                    "Do not add anything new. Return either the requested JSON object OR simple HEADLINE:/TEXT: fields; "
                    "no analysis, no explanation, no service message.\n\nORIGINAL TASK:\n"
                    + prompt[:7000]
                    + "\n\nPREVIOUS RESPONSE:\n"
                    + str(route.text)[:2600]
                )
                try:
                    repaired = _same_provider_repair(
                        route,
                        repair_prompt,
                        evidence,
                        language=language,
                        timeout=repair_timeout,
                        cancel_event=cancel_event,
                    )
                    if repaired.guard.allowed:
                        logger.info(
                            "RC17 one-shot Fact Guard repair success provider=%s model=%s",
                            repaired.route.provider,
                            repaired.route.model,
                        )
                        return repaired
                    failures.append(
                        f"{repaired.route.label} repair Fact Guard: " + "; ".join(repaired.guard.issues[:3])
                    )
                except Exception as repair_exc:
                    failures.append(f"{route.label} repair: {repair_exc}")

        if structural_error is not None:
            failures.append(f"{route.label}: {structural_error}")
            remaining = _remaining(deadline)

            if (
                not format_repair_used
                and provider in {"codex", "gemini"}
                and (remaining is None or remaining >= 14)
            ):
                format_repair_used = True
                repair_timeout = min(20, remaining) if remaining is not None else 20
                repair_prompt = (
                    "FORMAT REPAIR ONLY. The previous answer contains a news rewrite but failed parsing/structural QA: "
                    + str(structural_error)[:420]
                    + ". Do not change or add factual claims. Return either one JSON object with headline/rewrite fields OR "
                    "HEADLINE:/TEXT: fields. No analysis or explanation.\n\nORIGINAL TASK:\n"
                    + prompt[:7000]
                    + "\n\nPREVIOUS RESPONSE:\n"
                    + str(route.text)[:2600]
                )
                try:
                    repaired = _same_provider_repair(
                        route,
                        repair_prompt,
                        evidence,
                        language=language,
                        timeout=repair_timeout,
                        cancel_event=cancel_event,
                    )
                    if repaired.guard.allowed:
                        logger.info(
                            "RC17 one-shot format repair success provider=%s model=%s",
                            repaired.route.provider,
                            repaired.route.model,
                        )
                        return repaired
                    failures.append(
                        f"{repaired.route.label} format repair Fact Guard: " + "; ".join(repaired.guard.issues[:3])
                    )
                except Exception as repair_exc:
                    failures.append(f"{route.label} format repair: {repair_exc}")

            if provider == "local" and not local_repair_used:
                local_repair_used = True
                remaining = _remaining(deadline)
                if remaining is None or remaining >= 10:
                    repair_prompt = (
                        local_prompt
                        + "\n\nВИПРАВ ЛИШЕ ФОРМАТ попередньої відповіді. Не додавай фактів. "
                        "Поверни ЗАГОЛОВОК: і ТЕКСТ: без пояснень.\nПОПЕРЕДНЯ ВІДПОВІДЬ:\n"
                        + str(route.text)[:2200]
                    )
                    try:
                        repaired = _same_provider_repair(
                            route,
                            repair_prompt,
                            evidence,
                            language=language,
                            timeout=min(24, remaining) if remaining is not None else 24,
                            cancel_event=cancel_event,
                        )
                        if repaired.guard.allowed:
                            return repaired
                    except Exception as repair_exc:
                        failures.append(f"local format repair: {repair_exc}")

        if provider == "local":
            provider_skip.add("local")
        elif route.model:
            model_skip.add(str(route.model).casefold())
        elif provider:
            provider_skip.add(provider)

    if deadline is not None and time.monotonic() >= deadline:
        failures.append("спільний ліміт часу рерайту вичерпано")

    # Keep the dialog useful.  Three recent reasons are enough to diagnose the
    # failure; dumping every nested provider attempt was unreadable in RC16.
    raise AIRouterError(
        "AI-провайдери відповіли, але безпечний рерайт не пройшов post-AI QA. "
        + " | ".join(failures[-3:])
    )
