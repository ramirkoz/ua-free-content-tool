from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Sequence

from .ai_router import AIRouterError
from .editorial_memory import EditorialExample
from .evidence_pack import EvidencePack
from .models import NewsGroup
from . import rewrite_pipeline_v1_3 as base
from . import rewrite_pipeline_v1_4_rc17 as rc17

logger = logging.getLogger("content_agent.rewrite.rc26")


def _extract_jsonish_string(raw: str, key: str) -> str:
    """Recover an explicit quoted field from mildly malformed/truncated JSON."""
    text = base._clean_json_text(raw)
    match = re.search(rf'(?is)["\']{re.escape(key)}["\']\s*:\s*"', text)
    if not match:
        return ""
    chars: list[str] = []
    escaped = False
    for char in text[match.end() :]:
        if escaped:
            chars.append("\\" + char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            break
        chars.append(char)
    value = "".join(chars)
    encoded = value.replace("\r", "\\r").replace("\n", "\\n")
    try:
        return str(json.loads('"' + encoded + '"')).strip()
    except json.JSONDecodeError:
        return (
            value.replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
            .strip()
        )


def _canonical_payload(payload: object) -> dict[str, object] | None:
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        payload = payload[0]
    if not isinstance(payload, dict):
        return None
    for key in ("result", "output", "data"):
        nested = payload.get(key)
        if isinstance(nested, dict) and not any(
            payload.get(field) for field in ("headline", "title", "rewrite", "text")
        ):
            payload = nested
            break
    row = dict(payload)
    if not row.get("headline"):
        row["headline"] = row.get("title") or row.get("heading") or ""
    if not row.get("rewrite"):
        row["rewrite"] = (
            row.get("text")
            or row.get("body")
            or row.get("article")
            or row.get("telegram_post")
            or row.get("content")
            or ""
        )
    return row


def decode_payload_rc26(raw: str) -> dict[str, object]:
    """Tolerant envelope decoder; normal editorial QA + Fact Guard still apply."""
    text = base._clean_json_text(raw)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    canonical = _canonical_payload(parsed)
    if canonical is not None:
        return canonical

    in_string = False
    escaped = False
    depth = 0
    start = -1
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    parsed = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    parsed = None
                canonical = _canonical_payload(parsed)
                if canonical is not None:
                    return canonical
                start = -1

    headline = _extract_jsonish_string(text, "headline") or _extract_jsonish_string(text, "title")
    rewrite = (
        _extract_jsonish_string(text, "rewrite")
        or _extract_jsonish_string(text, "text")
        or _extract_jsonish_string(text, "body")
        or _extract_jsonish_string(text, "content")
    )
    fact_card = _extract_jsonish_string(text, "fact_card")
    if headline and rewrite:
        return {"headline": headline, "fact_card": fact_card, "rewrite": rewrite}

    prefix = r"(?:#{1,6}\s*)?(?:[-*]\s*)?(?:\*{1,2}|_{1,2})?"
    suffix = r"(?:\*{1,2}|_{1,2})?"
    headline_match = re.search(
        rf"(?im)^\s*{prefix}(?:ЗАГОЛОВОК|HEADLINE)\s*:\s*{suffix}\s*(.+?)\s*$",
        text,
    )
    rewrite_match = re.search(
        rf"(?ims)^\s*{prefix}(?:ТЕКСТ|TEXT|РЕРАЙТ|ARTICLE)\s*:\s*{suffix}\s*(.+)\Z",
        text,
    )
    if rewrite_match:
        rewrite = rewrite_match.group(1).strip()
        headline = headline_match.group(1).strip() if headline_match else ""
        if not headline and rewrite:
            compact = " ".join(rewrite.split())
            headline = re.split(r"(?<=[.!?…])\s+", compact, maxsplit=1)[0][:180].rstrip(" .!?…")
        if headline and rewrite:
            return {"headline": headline, "fact_card": "", "rewrite": rewrite}

    plain = text.strip()
    plain = re.sub(
        r"(?is)^\s*(?:ось|here(?:'s| is)|готовий|final)\s+(?:готовий\s+)?(?:рерайт|rewrite|текст|text)\s*[:\-]\s*",
        "",
        plain,
        count=1,
    ).strip()
    if plain and not base._FORBIDDEN_LINE.search(plain) and not plain.startswith(("{", "[")):
        compact = " ".join(plain.split())
        if len(compact) >= 40:
            headline = re.split(r"(?<=[.!?…])\s+", compact, maxsplit=1)[0][:180].rstrip(" .!?…")
            if headline:
                return {"headline": headline, "fact_card": "", "rewrite": plain}

    raise AIRouterError("AI повернув рерайт не у валідному або відновлюваному форматі.")


def cloud_prompt_rc26(
    group: NewsGroup,
    evidence: EvidencePack,
    examples: Sequence[EditorialExample],
    graph_memory: str,
    *,
    language: str,
) -> str:
    del group
    memory = base._style_memory(examples, graph_memory, language=language)
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
2. Preserve uncertainty and attribution at the same strength.
3. Do not add unsupported dates, numbers, entities, models, records or superlatives.
4. Use the unique facts in the evidence pack; do not invent compromises between conflicting sources.
5. One shared public text for all platforms, 1–4 short paragraphs, HARD MAXIMUM 900 characters including spaces. Very short source material must stay short.
6. No URLs, hashtags, fundraising block, analysis, model explanations or unsupported speculation.
7. STYLE MEMORY is style only and can never supply facts.

Return exactly two labelled sections and nothing else. Do not use JSON or markdown:
HEADLINE: short neutral English headline
TEXT: ready public English text
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
2. Зберігай силу невизначеності й атрибуцію.
3. Не додавай непідтверджені дати, числа, сутності, моделі, рекорди або суперлативи.
4. Використовуй унікальні факти Evidence Pack; не вигадуй компроміс між суперечливими джерелами.
5. Один спільний публічний текст для всіх платформ: 1–4 короткі абзаци, ЖОРСТКО НЕ БІЛЬШЕ 900 символів разом із пробілами. Дуже коротку новину не роздувай.
6. Без URL, хештегів, донатного блока, аналітики, пояснень моделі та домислів.
7. РЕДАКЦІЙНА ПАМ'ЯТЬ є лише стилем і ніколи не може постачати факти.
8. Весь публічний текст українською; назви брендів/моделей можна лишати в оригіналі.

Поверни рівно дві секції й нічого більше. Не використовуй JSON або markdown:
ЗАГОЛОВОК: короткий нейтральний український заголовок
ТЕКСТ: готовий публічний текст
{memory_block}

ПОТОЧНИЙ SOURCE EVIDENCE PACK:
{evidence.text}
""".strip()


def candidate_after_router_rc26(
    prompt: str,
    local_prompt: str,
    evidence: EvidencePack,
    *,
    language: str,
    skip_providers: set[str] | None = None,
    max_candidates: int = 4,
    deadline: float | None = None,
    cancel_event: object | None = None,
):
    rc17.install_rc17_fact_guard()
    provider_skip = set(skip_providers or set())
    model_skip: set[str] = set()
    failures: list[str] = []
    fact_repair_used = False
    format_repair_used = False
    local_repair_used = False
    attempts = max(1, min(6, int(max_candidates) + 1))

    for _ in range(attempts):
        if cancel_event is not None and bool(getattr(cancel_event, "is_set", lambda: False)()):
            raise AIRouterError("AI-рерайт скасовано.")
        remaining = rc17._remaining(deadline)
        if remaining is not None and remaining < 4:
            break
        try:
            route = base._router_call(
                prompt,
                local_prompt,
                skip_providers=provider_skip,
                skip_models=model_skip,
                task_timeout_seconds=min(base.REWRITE_PROFILE.task_timeout_seconds, remaining) if remaining is not None else None,
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
        candidate = None
        try:
            candidate = base._candidate(route, evidence, language=language)
        except Exception as exc:
            structural_error = exc

        if candidate is not None:
            if candidate.guard.allowed:
                return candidate
            guard_reason = "; ".join(candidate.guard.issues[:4])
            failures.append(f"{route.label}: Fact Guard: {guard_reason}")
            remaining = rc17._remaining(deadline)
            if (
                not fact_repair_used
                and provider in rc17._FACT_REPAIR_PROVIDERS
                and (remaining is None or remaining >= 16)
            ):
                fact_repair_used = True
                repair_prompt = (
                    "FACT-SAFE REPAIR. Re-read CURRENT SOURCE EVIDENCE in the original task. "
                    "The previous public rewrite is structurally usable but Fact Guard found: "
                    + guard_reason[:700]
                    + ". Correct or remove ONLY unsupported factual elements. Keep supported facts and attribution. "
                    "Do not add anything new. Return HEADLINE:/TEXT: fields only; no analysis or explanation.\n\nORIGINAL TASK:\n"
                    + prompt[:7000]
                    + "\n\nPREVIOUS RESPONSE:\n"
                    + str(route.text)[:2600]
                )
                try:
                    repaired = rc17._same_provider_repair(
                        route,
                        repair_prompt,
                        evidence,
                        language=language,
                        timeout=min(26, remaining) if remaining is not None else 26,
                        cancel_event=cancel_event,
                    )
                    if repaired.guard.allowed:
                        return repaired
                    failures.append(
                        f"{repaired.route.label} repair Fact Guard: " + "; ".join(repaired.guard.issues[:3])
                    )
                except Exception as repair_exc:
                    failures.append(f"{route.label} repair: {repair_exc}")

        if structural_error is not None:
            failures.append(f"{route.label}: {structural_error}")
            remaining = rc17._remaining(deadline)
            if (
                not format_repair_used
                and provider in (rc17._KNOWN_PROVIDERS - {"local"})
                and (remaining is None or remaining >= 10)
            ):
                format_repair_used = True
                repair_prompt = (
                    "FORMAT REPAIR ONLY. The previous answer contains a news rewrite but failed parsing/structural QA: "
                    + str(structural_error)[:420]
                    + ". Do not change or add factual claims. Return HEADLINE:/TEXT: fields only. "
                    "No JSON, analysis or explanation.\n\nORIGINAL TASK:\n"
                    + prompt[:7000]
                    + "\n\nPREVIOUS RESPONSE:\n"
                    + str(route.text)[:2600]
                )
                try:
                    repaired = rc17._same_provider_repair(
                        route,
                        repair_prompt,
                        evidence,
                        language=language,
                        timeout=min(16, remaining) if remaining is not None else 16,
                        cancel_event=cancel_event,
                    )
                    if repaired.guard.allowed:
                        return repaired
                    failures.append(
                        f"{repaired.route.label} format repair Fact Guard: " + "; ".join(repaired.guard.issues[:3])
                    )
                except Exception as repair_exc:
                    failures.append(f"{route.label} format repair: {repair_exc}")

            if provider == "local" and not local_repair_used:
                local_repair_used = True
                remaining = rc17._remaining(deadline)
                if remaining is None or remaining >= 10:
                    repair_prompt = (
                        local_prompt
                        + "\n\nВИПРАВ ЛИШЕ ФОРМАТ попередньої відповіді. Не додавай фактів. "
                        "Поверни ЗАГОЛОВОК: і ТЕКСТ: без пояснень.\nПОПЕРЕДНЯ ВІДПОВІДЬ:\n"
                        + str(route.text)[:2200]
                    )
                    try:
                        repaired = rc17._same_provider_repair(
                            route,
                            repair_prompt,
                            evidence,
                            language=language,
                            timeout=min(20, remaining) if remaining is not None else 20,
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
    raise AIRouterError(
        "AI-провайдери відповіли, але безпечний рерайт не пройшов post-AI QA. "
        + " | ".join(failures[-3:])
    )


def install_runtime() -> None:
    rc17.install_rc17_fact_guard()
    base._decode_payload = decode_payload_rc26
    base._cloud_prompt = cloud_prompt_rc26
    base._candidate_after_router = candidate_after_router_rc26
