from __future__ import annotations

import re
from typing import Iterable

from .ai_router_v1_2_2 import AIRouterError, run_ai
from .global_duplicates_v1_3_rc6 import (
    DuplicateCluster,
    _candidate_edges,
    _clean_title,
    _feedback_text,
    _plain_group_text,
    _select_non_overlapping,
    build_global_duplicate_batches,
    parse_duplicate_clusters as parse_legacy_json_clusters,
)
from .models import NewsGroup

_MAX_PROMPT_CHARS = 4_500
_CLOUD_OUTPUT_TOKENS = 420
_LOCAL_OUTPUT_TOKENS = 220
_LOCAL_TIMEOUT_SECONDS = 90

_MERGE_LINE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:MERGE|ОБ['’]?ЄДНАТИ|ОБЪЕДИНИТЬ)\s*:?\s*"
    r"(?P<ids>\d+(?:\s*[,;+]\s*\d+)+)"
    r"(?:\s*\|\s*(?P<confidence>\d{1,3})\s*%?)?"
    r"(?:\s*\|\s*(?P<reason>[^\r\n]+))?\s*$"
)
_NONE = re.compile(r"(?is)^\s*(?:NONE|NO\s+DUPLICATES|НЕМАЄ|НЕТ)\s*[.!]?\s*$")

_LAST_DUPLICATE_SEARCH_MODE = "AI Router"


def last_duplicate_search_label() -> str:
    return _LAST_DUPLICATE_SEARCH_MODE


def _records(groups: list[NewsGroup], *, max_chars: int, title_limit: int, text_limit: int) -> str:
    rows: list[str] = []
    for group in groups:
        rows.append(
            " | ".join(
                (
                    f"ID={group.id}",
                    f"ЧАС={group.last_published_at or group.updated_at or 'невідомо'}",
                    f"ЗАГОЛОВОК={_clean_title(group.canonical_title, title_limit)}",
                    f"ТЕКСТ={_plain_group_text(group, text_limit)}",
                )
            )
        )
    return "\n".join(rows)[:max_chars]


def build_global_duplicate_prompt(
    groups: list[NewsGroup],
    *,
    feedback: Iterable[dict[str, object]] = (),
    graph_memory: str = "",
    max_chars: int = _MAX_PROMPT_CHARS,
) -> str:
    """Compact same-event classifier used by all cloud providers in RC5."""
    if len(groups) < 2:
        return ""

    extras: list[str] = []
    feedback_block = _feedback_text(feedback, limit=6)
    if feedback_block:
        extras.append("ПРИКЛАДИ РІШЕНЬ РЕДАКТОРА:\n" + feedback_block)
    compact_graph = " ".join(str(graph_memory or "").split())[:500]
    if compact_graph:
        extras.append("ПАМ'ЯТЬ ПРАВИЛ (НЕ ДЖЕРЕЛО ФАКТІВ):\n" + compact_graph)

    header = (
        "Порівняй наведені блоки. Запропонуй об'єднання ЛИШЕ якщо це та сама конкретна подія "
        "або пряме уточнення тієї самої події. Одна тема, країна, людина чи організація не є дублікатом. "
        "Сумнівні пари не об'єднуй. Один ID може бути тільки в одному рядку.\n"
        "Відповідь тільки рядками: MERGE 12,18 | 91 | коротка причина. "
        "Для трьох блоків: MERGE 12,18,24 | 88 | коротка причина. "
        "Якщо дублікатів немає: NONE. Без JSON, markdown і додаткових пояснень.\n"
    )
    if extras:
        header += "\n" + "\n".join(extras) + "\n"
    header += f"\nБЛОКИ ({len(groups)}):\n"

    remaining = max(600, max_chars - len(header))
    per_group = max(80, min(240, remaining // max(1, len(groups)) - 70))
    prompt = header + _records(
        groups,
        max_chars=remaining,
        title_limit=180,
        text_limit=per_group,
    )
    return prompt[:max_chars]


def build_local_duplicate_prompt(groups: list[NewsGroup], *, max_chars: int = 3_200) -> str:
    if len(groups) < 2:
        return ""
    header = (
        "Знайди тільки ту саму конкретну подію. Не об'єднуй просто схожу тему.\n"
        "Відповідь тільки рядками: MERGE 12,18 | 91 | причина. Якщо немає дублікатів: NONE. "
        "Без JSON, markdown і пояснень.\n"
    )
    remaining = max(500, max_chars - len(header))
    per_group = max(90, min(190, remaining // max(1, len(groups)) - 60))
    return (
        header
        + _records(groups, max_chars=remaining, title_limit=150, text_limit=per_group)
    )[:max_chars]


def _parse_line_clusters(raw: str, valid_ids: set[int]) -> list[DuplicateCluster] | None:
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:text|json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    if not text:
        return None
    if _NONE.fullmatch(text):
        return []

    matches = list(_MERGE_LINE.finditer(text))
    if not matches:
        return None

    result: list[DuplicateCluster] = []
    used: set[int] = set()
    for match in matches:
        ids: list[int] = []
        for token in re.split(r"\s*[,;+]\s*", match.group("ids")):
            try:
                group_id = int(token)
            except ValueError:
                continue
            if group_id in valid_ids and group_id not in ids and group_id not in used:
                ids.append(group_id)
        try:
            confidence = max(0, min(100, int(match.group("confidence") or 75)))
        except ValueError:
            confidence = 75
        if len(ids) < 2 or confidence < 55:
            continue
        reason = " ".join(str(match.group("reason") or "та сама подія").split())[:500]
        result.append(DuplicateCluster(tuple(ids), confidence, reason))
        used.update(ids)
    return sorted(result, key=lambda item: (-item.confidence, item.group_ids))


def parse_duplicate_clusters(raw: str, valid_ids: set[int]) -> list[DuplicateCluster]:
    """Accept the RC5 line protocol and remain backward-compatible with RC4 JSON."""
    lines = _parse_line_clusters(raw, valid_ids)
    if lines is not None:
        return lines
    try:
        return parse_legacy_json_clusters(raw, valid_ids)
    except AIRouterError as exc:
        raise AIRouterError("AI повернув відповідь про дублікати у нерозпізнаному форматі.") from exc


def _run_duplicate_router(prompt: str, local_prompt: str, *, validator):
    try:
        return run_ai(
            prompt,
            validator=validator,
            max_output_tokens=_CLOUD_OUTPUT_TOKENS,
            local_prompt=local_prompt,
            local_max_output_tokens=_LOCAL_OUTPUT_TOKENS,
            local_timeout_seconds=_LOCAL_TIMEOUT_SECONDS,
            local_repair=False,
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        return run_ai(prompt, validator=validator, max_output_tokens=_CLOUD_OUTPUT_TOKENS)


def _fallback_clusters_from_candidates(groups: list[NewsGroup]) -> list[DuplicateCluster]:
    """Review-only local candidates used when every AI route fails.

    Nothing is merged automatically. The existing deterministic prefilter already
    identified pairs worth checking, so a provider outage must not make the button
    useless. The editor still approves or rejects every proposed merge in the UI.
    """
    result: list[DuplicateCluster] = []
    used: set[int] = set()
    for edge in _candidate_edges(groups):
        left = groups[edge.left]
        right = groups[edge.right]
        if left.id in used or right.id in used:
            continue
        confidence = max(55, min(82, int(round(55 + max(0.0, edge.score - 0.11) * 55))))
        result.append(
            DuplicateCluster(
                (left.id, right.id),
                confidence,
                "Локальний кандидат за схожістю заголовка/тексту; AI недоступний або повернув непридатний формат.",
            )
        )
        used.update((left.id, right.id))
    return result


def find_global_duplicate_clusters(
    groups: list[NewsGroup],
    *,
    feedback: Iterable[dict[str, object]] = (),
    graph_memory: str = "",
) -> list[DuplicateCluster]:
    global _LAST_DUPLICATE_SEARCH_MODE
    if len(groups) < 2:
        _LAST_DUPLICATE_SEARCH_MODE = "локальний аналіз"
        return []

    batches = build_global_duplicate_batches(groups)
    if not batches:
        _LAST_DUPLICATE_SEARCH_MODE = "локальний prefilter"
        return []

    proposals: list[DuplicateCluster] = []
    used_local_fallback = False
    for batch in batches:
        valid_ids = {group.id for group in batch}
        prompt = build_global_duplicate_prompt(batch, feedback=feedback, graph_memory=graph_memory)
        local_prompt = build_local_duplicate_prompt(batch)

        def validate(raw: str, ids: set[int] = valid_ids) -> None:
            parse_duplicate_clusters(raw, ids)

        try:
            routed = _run_duplicate_router(prompt, local_prompt, validator=validate)
            proposals.extend(parse_duplicate_clusters(routed.text, valid_ids))
        except AIRouterError:
            used_local_fallback = True
            proposals.extend(_fallback_clusters_from_candidates(batch))

    _LAST_DUPLICATE_SEARCH_MODE = "локальні кандидати без AI" if used_local_fallback else "AI Router"
    return _select_non_overlapping(proposals)
