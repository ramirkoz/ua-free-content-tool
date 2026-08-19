from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

from .ai_router_v1_2_2 import AIRouterError, AIResult, run_ai
from .ai_task_profiles import REWRITE_PROFILE
from .editorial_memory import EditorialExample, format_examples_for_prompt
from .evidence_pack import EvidencePack, build_evidence_pack
from .fact_guard import FactGuardResult, guard_rewrite
from .i18n import normalize_language
from .models import NewsGroup, RewriteResult
from .publication_text import validate_editorial_text
from .rewriter import platform_texts_from_base

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_FORBIDDEN_LINE = re.compile(
    r"(?im)^\s*(?:ЗАГОЛОВОК|HEADLINE|ФАКТИ|FACTS|FACT CARD|АНАЛІЗ|ANALYSIS|ПОЯСНЕННЯ|EXPLANATION)\s*:"
)
_LAST_ENGINE_LABEL = ""
_LAST_DIAGNOSTIC = ""


@dataclass(frozen=True, slots=True)
class RewriteCandidate:
    headline: str
    rewrite: str
    model_fact_card: str
    route: AIResult
    guard: FactGuardResult


def last_rewrite_engine_label() -> str:
    return _LAST_ENGINE_LABEL


def last_rewrite_diagnostic() -> str:
    return _LAST_DIAGNOSTIC


def _set_last(candidate: RewriteCandidate, evidence: EvidencePack, *, second_pass: bool) -> None:
    global _LAST_ENGINE_LABEL, _LAST_DIAGNOSTIC
    _LAST_ENGINE_LABEL = candidate.route.label
    pass_label = "2 проходи" if second_pass else "1 прохід"
    trunc = " · pack скорочено" if evidence.truncated else ""
    _LAST_DIAGNOSTIC = (
        f"Fact Guard PASS · quality {candidate.guard.score}/100 · {pass_label} · "
        f"evidence {evidence.selected_sentences}/{evidence.total_sentences} речень{trunc}"
    )


def _clean_json_text(raw: str) -> str:
    value = str(raw or "").strip()
    value = re.sub(r"(?is)<think>.*?</think>", "", value).strip()
    return _CODE_FENCE.sub("", value).strip()


def _decode_payload(raw: str) -> dict[str, object]:
    text = _clean_json_text(raw)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        # Accept common provider aliases while keeping one canonical internal shape.
        if not payload.get("headline"):
            payload["headline"] = payload.get("title") or payload.get("heading") or ""
        if not payload.get("rewrite"):
            payload["rewrite"] = (
                payload.get("text") or payload.get("body") or payload.get("article")
                or payload.get("telegram_post") or payload.get("content") or ""
            )
        return payload

    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            if not payload.get("headline"):
                payload["headline"] = payload.get("title") or payload.get("heading") or ""
            if not payload.get("rewrite"):
                payload["rewrite"] = (payload.get("text") or payload.get("body") or payload.get("article") or payload.get("telegram_post") or payload.get("content") or "")
            return payload

    headline_match = re.search(r"(?im)^\s*(?:ЗАГОЛОВОК|HEADLINE)\s*:\s*(.+?)\s*$", text)
    rewrite_match = re.search(r"(?ims)^\s*(?:ТЕКСТ|TEXT|РЕРАЙТ|ARTICLE)\s*:\s*(.+)\Z", text)
    if rewrite_match:
        rewrite = rewrite_match.group(1).strip()
        headline = headline_match.group(1).strip() if headline_match else ""
        if not headline and rewrite:
            headline = rewrite.splitlines()[0][:180].rstrip(" .!?…")
        if headline and rewrite:
            return {"headline": headline, "fact_card": "", "rewrite": rewrite}

    # Last-resort recovery: some otherwise useful models ignore wrapper labels and
    # return only the public body. Accept that only when it contains no service sections.
    plain = text.strip()
    if plain and not _FORBIDDEN_LINE.search(plain) and not plain.startswith(("{", "[")):
        compact = " ".join(plain.split())
        if len(compact) >= 60:
            first_sentence = re.split(r"(?<=[.!?…])\s+", compact, maxsplit=1)[0]
            headline = first_sentence[:180].rstrip(" .!?…")
            return {"headline": headline, "fact_card": "", "rewrite": plain}

    raise AIRouterError("AI повернув рерайт не у валідному або відновлюваному форматі.")


def _parse_structural(raw: str) -> dict[str, object]:
    payload = _decode_payload(raw)
    headline = str(payload.get("headline") or "").strip()
    rewrite = str(payload.get("rewrite") or "").strip()
    if not headline or not rewrite:
        raise AIRouterError("AI не повернув заголовок або текст рерайту.")
    if _FORBIDDEN_LINE.search(rewrite) or rewrite.startswith(("{", "[")):
        raise AIRouterError("AI змішав службові секції з публічним текстом.")
    validate_editorial_text(rewrite)
    return payload


def _validate_structural(raw: str) -> None:
    _parse_structural(raw)


def _style_memory(
    examples: Sequence[EditorialExample],
    graph_memory: str,
    *,
    language: str,
    max_chars: int = 3600,
) -> str:
    parts: list[str] = []
    examples_text = format_examples_for_prompt(examples, language=language)
    if examples_text:
        parts.append(examples_text)
    if graph_memory:
        parts.append(str(graph_memory).strip())
    text = "\n\n--- STYLE MEMORY ---\n\n".join(part for part in parts if part)
    return text[:max_chars]


def _cloud_prompt(
    group: NewsGroup,
    evidence: EvidencePack,
    examples: Sequence[EditorialExample],
    graph_memory: str,
    *,
    language: str,
) -> str:
    del group
    memory = _style_memory(examples, graph_memory, language=language)
    if language == "en":
        memory_block = (
            "\n\nSTYLE MEMORY (NOT FACTUAL EVIDENCE):\n"
            "Use this only for tone, density and ordering. NEVER copy names, dates, numbers, events or claims from it.\n"
            + memory
            if memory
            else ""
        )
        return f"""
Create one concise UA FREE news rewrite from the CURRENT SOURCE EVIDENCE PACK below.

HARD RULES:
1. CURRENT SOURCE EVIDENCE PACK is the only factual authority.
2. Preserve uncertainty and attribution at the same strength. A plan is not a launch; an estimate is not an established fact.
3. Do not add a year, date, number, percentage, company, person, product/model, record, world-first, largest/fastest/most-powerful claim unless supported by the evidence pack.
4. Use facts from every represented source when they add unique information. Do not invent a compromise when sources conflict.
5. One shared public text for all platforms, 1–4 short paragraphs, maximum 900 characters including spaces. Very short source material must stay short.
6. No URLs, hashtags, fundraising block, analysis, model explanations or unsupported speculation.
7. STYLE MEMORY is style only and can never supply facts.

Return exactly one JSON object and nothing else:
{{"headline":"neutral English headline","fact_card":"short editor note","rewrite":"public English text"}}
{memory_block}

CURRENT SOURCE EVIDENCE PACK:
{evidence.text}
""".strip()

    memory_block = (
        "\n\nРЕДАКЦІЙНА ПАМ'ЯТЬ СТИЛЮ (НЕ ДЖЕРЕЛО ФАКТІВ):\n"
        "Використовуй лише тон, щільність і порядок викладу. НІКОЛИ не перенось звідси імена, дати, числа, події чи твердження.\n"
        + memory
        if memory
        else ""
    )
    return f"""
Створи один стислий новинний рерайт UA FREE за ПОТОЧНИМ EVIDENCE PACK нижче.

ЖОРСТКІ ПРАВИЛА:
1. ПОТОЧНИЙ EVIDENCE PACK є єдиним джерелом фактів.
2. Зберігай силу невизначеності й атрибуцію. План не є запуском; оцінка не є встановленим фактом; твердження компанії має лишатися атрибутованим.
3. Не додавай рік, дату, число, відсоток, компанію, особу, продукт/модель, рекорд, «перший у світі», «найбільший», «найшвидший» або «найпотужніший», якщо цього немає в Evidence Pack.
4. Використовуй унікальні факти з усіх представлених джерел. Якщо джерела суперечать одне одному, не вигадуй компроміс.
5. Один спільний публічний текст для всіх платформ: 1–4 короткі абзаци, максимум 900 символів разом із пробілами. Дуже коротку новину не роздувай.
6. Без URL, хештегів, донатного блока, аналітики, пояснень моделі та домислів.
7. РЕДАКЦІЙНА ПАМ'ЯТЬ є лише стилем і ніколи не може постачати факти.
8. Весь публічний текст українською; назви брендів/моделей можна лишати в оригіналі.

Поверни рівно один JSON-об'єкт і нічого більше:
{{"headline":"нейтральний український заголовок","fact_card":"коротка службова примітка","rewrite":"готовий публічний текст"}}
{memory_block}

ПОТОЧНИЙ SOURCE EVIDENCE PACK:
{evidence.text}
""".strip()


def _local_prompt(evidence: EvidencePack, *, language: str) -> str:
    if language == "en":
        return f"""
Write a precise English news rewrite using ONLY the CURRENT EVIDENCE below. Do not add facts, dates, numbers, companies, products, records or conclusions. Keep hedges/attribution. Maximum 900 characters.
Return exactly:
HEADLINE: short neutral headline
TEXT: public text

CURRENT EVIDENCE:
{evidence.text}
""".strip()
    return f"""
Зроби точний новинний рерайт українською, використовуючи ТІЛЬКИ ПОТОЧНІ ДОКАЗИ нижче. Не додавай фактів, дат, чисел, компаній, моделей, рекордів чи висновків. Зберігай невизначеність і атрибуцію. Максимум 900 символів.
Поверни рівно:
ЗАГОЛОВОК: короткий нейтральний заголовок
ТЕКСТ: готовий публічний текст

ПОТОЧНІ ДОКАЗИ:
{evidence.text}
""".strip()


def _router_call(
    prompt: str,
    local_prompt: str,
    *,
    skip_providers: set[str] | frozenset[str] = frozenset(),
    skip_models: set[str] | frozenset[str] = frozenset(),
) -> AIResult:
    """Transport-only Router call. Candidate QA happens after this function returns."""
    profile = REWRITE_PROFILE
    try:
        return run_ai(
            prompt,
            validator=None,
            max_output_tokens=profile.cloud_output_tokens,
            local_prompt=local_prompt,
            local_max_output_tokens=profile.local_output_tokens,
            local_timeout_seconds=profile.local_timeout_seconds,
            cloud_timeout_seconds=profile.cloud_timeout_seconds,
            task_timeout_seconds=profile.task_timeout_seconds,
            skip_providers=skip_providers,
            skip_models=skip_models,
            local_repair=False,
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        return run_ai(prompt, validator=None, max_output_tokens=profile.cloud_output_tokens)



def _candidate_after_router(
    prompt: str,
    local_prompt: str,
    evidence: EvidencePack,
    *,
    language: str,
    skip_providers: set[str] | None = None,
    max_candidates: int = 8,
) -> RewriteCandidate:
    """Get a provider response first, then apply structural/editorial/Fact Guard QA.

    A candidate rejected by post-AI QA never changes provider health or cooldown.
    We skip only the rejected model where possible, preserving other models from
    the same provider for the same news item.
    """
    provider_skip = set(skip_providers or set())
    model_skip: set[str] = set()
    failures: list[str] = []
    local_repair_done = False

    for _ in range(max(1, int(max_candidates))):
        try:
            route = _router_call(
                prompt,
                local_prompt,
                skip_providers=provider_skip,
                skip_models=model_skip,
            )
        except AIRouterError as exc:
            detail = " | ".join(failures[-5:])
            if detail:
                raise AIRouterError(
                    "AI-провайдери відповіли, але post-AI QA відхилив кандидати. "
                    + detail
                    + f" | Router: {exc}"
                ) from exc
            raise

        try:
            candidate = _candidate(route, evidence, language=language)
            if candidate.guard.allowed:
                return candidate
            failures.append(
                f"{route.label}: Fact Guard: " + "; ".join(candidate.guard.issues[:4])
            )
        except Exception as exc:
            failures.append(f"{route.label}: {exc}")

            if route.provider == "local" and not local_repair_done:
                local_repair_done = True
                repair_prompt = (
                    local_prompt
                    + "\n\nPOST-AI FORMAT REPAIR. Попередня відповідь була отримана, але не пройшла post-AI QA: "
                    + str(exc)[:500]
                    + "\nНе додавай нових фактів. Виправ лише формат, мову, завершеність і довжину. "
                    + "Поверни рівно ЗАГОЛОВОК і ТЕКСТ у форматі, який вимагався вище.\n\nПОПЕРЕДНЯ ВІДПОВІДЬ:\n"
                    + str(route.text)[:2600]
                )
                try:
                    repaired_route = _router_call(
                        repair_prompt,
                        repair_prompt,
                        skip_providers={"codex", "gemini", "nvidia", "sambanova", "cerebras", "groq", "openrouter", "cloudflare"},
                    )
                    repaired = _candidate(repaired_route, evidence, language=language)
                    if repaired.guard.allowed:
                        return repaired
                    failures.append(
                        "local repair Fact Guard: " + "; ".join(repaired.guard.issues[:4])
                    )
                except Exception as repair_exc:
                    failures.append(f"local repair: {repair_exc}")

        if route.provider == "local":
            provider_skip.add("local")
        elif route.model:
            model_skip.add(str(route.model).casefold())
        elif route.provider:
            provider_skip.add(str(route.provider).casefold())

    raise AIRouterError(
        "AI-провайдери відповіли, але post-AI QA відхилив усі кандидати. "
        + " | ".join(failures[-6:])
    )

def _candidate(route: AIResult, evidence: EvidencePack, *, language: str) -> RewriteCandidate:
    payload = _parse_structural(route.text)
    headline = str(payload.get("headline") or "").strip()
    rewrite = str(payload.get("rewrite") or "").strip()
    guard = guard_rewrite(evidence.text, headline, rewrite, language=language)
    return RewriteCandidate(
        headline=headline,
        rewrite=rewrite,
        model_fact_card=str(payload.get("fact_card") or "").strip(),
        route=route,
        guard=guard,
    )


def _fact_card(candidate: RewriteCandidate, evidence: EvidencePack, *, language: str) -> str:
    text = " ".join(candidate.rewrite.split())
    if len(text) > 430:
        cut = max(text.rfind(". ", 0, 430), text.rfind("! ", 0, 430), text.rfind("? ", 0, 430))
        if cut >= 100:
            text = text[: cut + 1]
        else:
            cut = text.rfind(" ", 0, 426)
            text = text[: max(100, cut)].rstrip(" ,;:-") + "…"
    if language == "en":
        prefix = (
            f"Sources: {evidence.source_count}. Fact Guard: PASS · quality {candidate.guard.score}/100 · "
            f"evidence sentences {evidence.selected_sentences}/{evidence.total_sentences}."
        )
    else:
        prefix = (
            f"Джерел: {evidence.source_count}. Fact Guard: PASS · quality {candidate.guard.score}/100 · "
            f"речень Evidence Pack {evidence.selected_sentences}/{evidence.total_sentences}."
        )
    return f"{prefix}\n{text}".strip()


def rewrite_group_v13(
    group: NewsGroup,
    examples: Sequence[EditorialExample],
    *,
    graph_memory: str = "",
    language: str = "uk",
) -> RewriteResult:
    """Evidence-first adaptive production rewrite for Content Tool 1.3."""

    language = normalize_language(language)
    cloud_evidence = build_evidence_pack(group, max_chars=REWRITE_PROFILE.cloud_evidence_chars)
    local_evidence = build_evidence_pack(group, max_chars=REWRITE_PROFILE.local_evidence_chars)
    if not cloud_evidence.text:
        raise AIRouterError("У поточному блоці немає тексту для рерайту.")

    prompt = _cloud_prompt(group, cloud_evidence, examples, graph_memory, language=language)
    local_prompt = _local_prompt(local_evidence, language=language)
    first = _candidate_after_router(
        prompt,
        local_prompt,
        cloud_evidence,
        language=language,
    )

    candidates: list[RewriteCandidate] = [first]

    second_needed = first.guard.score < REWRITE_PROFILE.second_pass_threshold
    second_attempted = False
    second_error = ""
    if second_needed:
        feedback = "; ".join(first.guard.issues[:4]) if first.guard.issues else f"quality score {first.guard.score}/100"
        reinforced = (
            prompt
            + "\n\nSECOND PASS CONTROL: The previous candidate was rejected or rated weak because: "
            + feedback
            + ". Do not copy the previous answer. Re-read CURRENT SOURCE EVIDENCE PACK and produce a cleaner candidate."
        )
        try:
            second = _candidate_after_router(
                reinforced,
                local_prompt,
                cloud_evidence,
                language=language,
                skip_providers={first.route.provider},
                max_candidates=6,
            )
            second_attempted = True
            candidates.append(second)
        except AIRouterError as exc:
            second_error = str(exc)

    if not candidates:
        issues = "; ".join(first.guard.issues[:5]) or "кандидат не пройшов Fact Guard"
        if second_error:
            issues += f"; другий провайдер недоступний: {second_error}"
        raise AIRouterError("Рерайт заблоковано Fact Guard: " + issues)

    chosen = max(candidates, key=lambda item: item.guard.score)
    _set_last(chosen, cloud_evidence, second_pass=second_attempted)
    return RewriteResult(
        headline=chosen.headline,
        fact_card=_fact_card(chosen, cloud_evidence, language=language),
        rewrite=chosen.rewrite,
        platform_texts=platform_texts_from_base(
            chosen.rewrite,
            include_source_link=bool(group.include_source_link),
            source_url=group.primary_url,
        ),
        source_count_used=len(group.articles),
        source_count_total=len(group.articles),
        auto_compacted=False,
    )
