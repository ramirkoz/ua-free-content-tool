from __future__ import annotations

import logging
import time

from .ai_router_v1_2_1 import AIRouterError
from .ai_task_profiles import REWRITE_PROFILE
from .evidence_pack import EvidencePack
from .rewrite_pipeline_v1_3 import RewriteCandidate
from . import rewrite_pipeline_v1_3 as base

logger = logging.getLogger("content_agent.rewrite.rc16")

_KNOWN_PROVIDERS = frozenset({"codex", "gemini", "nvidia", "groq", "cloudflare", "local"})
_FACT_REPAIR_PROVIDERS = frozenset({"codex", "gemini", "nvidia", "groq", "cloudflare"})


def candidate_after_router_rc16(
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
    """RC16 candidate loop with one same-provider Fact Guard correction pass.

    A provider that returned a structurally healthy answer is not discarded
    immediately just because one factual field failed the deterministic guard.
    The same provider gets one tightly scoped correction attempt before the
    router spends another model/provider. The corrected text must pass the same
    structural checks and Fact Guard; no safety rule is bypassed.
    """

    provider_skip = set(skip_providers or set())
    model_skip: set[str] = set()
    failures: list[str] = []
    local_repair_done = False
    provider_format_repair_done: set[str] = set()
    provider_fact_repair_done: set[str] = set()

    for _ in range(max(1, int(max_candidates))):
        if cancel_event is not None and bool(getattr(cancel_event, "is_set", lambda: False)()):
            raise AIRouterError("AI-рерайт скасовано.")
        remaining = None if deadline is None else int(deadline - time.monotonic())
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
            detail = " | ".join(failures[-4:])
            if detail:
                raise AIRouterError(
                    "AI-провайдери відповіли, але post-AI QA відхилив кандидати. " + detail + f" | Router: {exc}"
                ) from exc
            raise

        candidate: RewriteCandidate | None = None
        structural_error: Exception | None = None
        try:
            candidate = base._candidate(route, evidence, language=language)
        except Exception as exc:
            structural_error = exc

        if candidate is not None:
            if candidate.guard.allowed:
                return candidate

            guard_reason = "; ".join(candidate.guard.issues[:4])
            failures.append(f"{route.label}: Fact Guard: {guard_reason}")

            remaining = None if deadline is None else int(deadline - time.monotonic())
            provider = str(route.provider or "").casefold()
            if (
                provider in _FACT_REPAIR_PROVIDERS
                and provider not in provider_fact_repair_done
                and (remaining is None or remaining >= 9)
            ):
                provider_fact_repair_done.add(provider)
                repair_prompt = (
                    prompt
                    + "\n\nFACT GUARD REPAIR ONLY. The previous public rewrite was structurally valid but "
                    + "the deterministic factual guard rejected it for exactly these reasons: "
                    + guard_reason[:700]
                    + ". Re-read CURRENT SOURCE EVIDENCE. Correct or remove ONLY the unsupported factual element(s). "
                    + "Do not add new facts, do not strengthen claims, and keep all supported facts. Return exactly the requested output envelope."
                    + "\nPREVIOUS RESPONSE:\n" + str(route.text)[:2600]
                )
                try:
                    repaired_route = base._router_call(
                        repair_prompt,
                        repair_prompt,
                        skip_providers=set(_KNOWN_PROVIDERS) - {provider},
                        task_timeout_seconds=min(14, remaining) if remaining is not None else 14,
                        cancel_event=cancel_event,
                    )
                    repaired = base._candidate(repaired_route, evidence, language=language)
                    if repaired.guard.allowed:
                        logger.info(
                            "RC16 same-provider Fact Guard repair success provider=%s model=%s",
                            repaired_route.provider,
                            repaired_route.model,
                        )
                        return repaired
                    failures.append(
                        f"{repaired_route.label} fact repair Fact Guard: "
                        + "; ".join(repaired.guard.issues[:4])
                    )
                except Exception as repair_exc:
                    failures.append(f"{route.label} fact repair: {repair_exc}")

        if structural_error is not None:
            exc = structural_error
            failures.append(f"{route.label}: {exc}")
            remaining = None if deadline is None else int(deadline - time.monotonic())
            provider = str(route.provider or "").casefold()
            if (
                provider in {"codex", "gemini"}
                and provider not in provider_format_repair_done
                and (remaining is None or remaining >= 9)
            ):
                provider_format_repair_done.add(provider)
                repair_prompt = (
                    prompt
                    + "\n\nFORMAT REPAIR ONLY. The previous response failed parsing/QA because: "
                    + str(exc)[:420]
                    + "\nDo not add or change facts. Re-read CURRENT SOURCE EVIDENCE and return exactly the requested output envelope."
                    + "\nPREVIOUS RESPONSE:\n" + str(route.text)[:2600]
                )
                try:
                    repaired_route = base._router_call(
                        repair_prompt,
                        repair_prompt,
                        skip_providers=set(_KNOWN_PROVIDERS) - {provider},
                        task_timeout_seconds=min(14, remaining) if remaining is not None else 14,
                        cancel_event=cancel_event,
                    )
                    repaired = base._candidate(repaired_route, evidence, language=language)
                    if repaired.guard.allowed:
                        logger.info(
                            "RC16 same-provider format repair success provider=%s model=%s",
                            repaired_route.provider,
                            repaired_route.model,
                        )
                        return repaired
                    failures.append(
                        f"{repaired_route.label} format repair Fact Guard: "
                        + "; ".join(repaired.guard.issues[:4])
                    )
                except Exception as repair_exc:
                    failures.append(f"{route.label} format repair: {repair_exc}")

            if provider == "local" and not local_repair_done:
                local_repair_done = True
                remaining = None if deadline is None else int(deadline - time.monotonic())
                if remaining is None or remaining >= 8:
                    repair_prompt = (
                        local_prompt
                        + "\n\nPOST-AI FORMAT REPAIR. Попередня відповідь не пройшла post-AI QA: "
                        + str(exc)[:400]
                        + "\nНе додавай нових фактів. Виправ лише формат, мову, завершеність і довжину."
                        + "\nПОПЕРЕДНЯ ВІДПОВІДЬ:\n" + str(route.text)[:2200]
                    )
                    try:
                        repaired_route = base._router_call(
                            repair_prompt,
                            repair_prompt,
                            skip_providers={"codex", "gemini", "nvidia", "groq", "cloudflare"},
                            task_timeout_seconds=min(25, remaining) if remaining is not None else 25,
                            cancel_event=cancel_event,
                        )
                        repaired = base._candidate(repaired_route, evidence, language=language)
                        if repaired.guard.allowed:
                            return repaired
                        failures.append("local repair Fact Guard: " + "; ".join(repaired.guard.issues[:4]))
                    except Exception as repair_exc:
                        failures.append(f"local repair: {repair_exc}")

        provider = str(route.provider or "").casefold()
        if provider == "local":
            provider_skip.add("local")
        elif route.model:
            model_skip.add(str(route.model).casefold())
        elif provider:
            provider_skip.add(provider)

    if deadline is not None and time.monotonic() >= deadline:
        failures.append("спільний ліміт часу рерайту вичерпано")
    raise AIRouterError(
        "AI-провайдери відповіли, але post-AI QA не знайшов придатного кандидата. " + " | ".join(failures[-5:])
    )
