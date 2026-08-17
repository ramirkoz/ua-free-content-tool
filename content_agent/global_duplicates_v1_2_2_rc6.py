from __future__ import annotations

import math
import re
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable

from .ai_router_v1_2_2 import AIRouterError, run_ai
from .global_duplicates_v1_3_rc6 import DuplicateCluster, _clean_title, _plain_group_text, _select_non_overlapping, _tokens
from .models import NewsGroup

_MAX_PROMPT_CHARS = 4_200
_CLOUD_OUTPUT_TOKENS = 360
_LOCAL_OUTPUT_TOKENS = 180
_CLOUD_TIMEOUT_SECONDS = 6
_LOCAL_TIMEOUT_SECONDS = 12
_GLOBAL_DEADLINE_SECONDS = 45
_MAX_AI_GROUPS = 12
_MAX_EDGES = 160
_NEIGHBORS_PER_GROUP = 4

_MERGE_LINE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:MERGE|ОБ['’]?ЄДНАТИ|ОБЪЕДИНИТЬ)\s*:?\s*"
    r"(?P<ids>\d+(?:\s*[,;+]\s*\d+)+)"
    r"(?:\s*\|\s*(?P<confidence>\d{1,3})\s*%?)?"
    r"(?:\s*\|\s*(?P<reason>[^\r\n]+))?\s*$"
)
_NONE = re.compile(r"(?is)^\s*(?:NONE|NO\s+DUPLICATES|НЕМАЄ|НЕТ)\s*[.!]?\s*$")
_LAST_DUPLICATE_SEARCH_MODE = "локальний prefilter"


class DuplicateSearchCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _FastEdge:
    left: int
    right: int
    score: float


def last_duplicate_search_label() -> str:
    return _LAST_DUPLICATE_SEARCH_MODE


def _check(cancel_event: threading.Event | None, deadline: float) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise DuplicateSearchCancelled("Пошук об'єднань скасовано користувачем.")
    if time.monotonic() >= deadline:
        raise DuplicateSearchCancelled("Пошук об'єднань завершено за лімітом часу.")


def _parse_time(group: NewsGroup) -> float | None:
    raw = group.last_published_at or group.updated_at or group.created_at
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _fast_candidate_edges(
    groups: list[NewsGroup],
    *,
    deadline: float,
    cancel_event: threading.Event | None = None,
) -> list[_FastEdge]:
    """Near-linear blocking prefilter. It avoids the old O(n²) all-pairs scan."""
    n = len(groups)
    if n < 2:
        return []

    title_sets: list[set[str]] = []
    token_sets: list[set[str]] = []
    numbers: list[set[str]] = []
    times: list[float | None] = []
    df: Counter[str] = Counter()
    normalized_titles: defaultdict[str, list[int]] = defaultdict(list)

    for index, group in enumerate(groups):
        if index % 64 == 0:
            _check(cancel_event, deadline)
        title = _clean_title(group.canonical_title, 260)
        title_tokens = set(_tokens(title))
        body_tokens = set(_tokens(_plain_group_text(group, 900)))
        all_tokens = title_tokens | body_tokens
        title_sets.append(title_tokens)
        token_sets.append(all_tokens)
        numbers.append({token for token in all_tokens if token.isdigit() and len(token) >= 2})
        times.append(_parse_time(group))
        df.update(all_tokens)
        title_key = " ".join(_tokens(title))[:180]
        if title_key:
            normalized_titles[title_key].append(index)

    postings: defaultdict[str, list[int]] = defaultdict(list)
    max_posting = max(12, min(48, n // 8 + 8))
    for index, tokens in enumerate(token_sets):
        ranked = sorted(
            (token for token in tokens if 1 < df[token] <= max_posting),
            key=lambda token: (0 if token in title_sets[index] else 1, df[token], -len(token), token),
        )[:18]
        for token in ranked:
            postings[token].append(index)

    pair_hits: Counter[tuple[int, int]] = Counter()
    for pos, members in enumerate(postings.values()):
        if pos % 64 == 0:
            _check(cancel_event, deadline)
        if len(members) < 2 or len(members) > max_posting:
            continue
        for i in range(len(members)):
            left = members[i]
            for j in range(i + 1, len(members)):
                right = members[j]
                pair_hits[(left, right)] += 1

    for members in normalized_titles.values():
        if 1 < len(members) <= 12:
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    pair_hits[(members[i], members[j])] += 4

    scored: list[_FastEdge] = []
    for pos, ((left, right), hits) in enumerate(pair_hits.items()):
        if pos % 128 == 0:
            _check(cancel_event, deadline)
        title_union = title_sets[left] | title_sets[right]
        title_j = len(title_sets[left] & title_sets[right]) / max(1, len(title_union))
        small = min(len(token_sets[left]), len(token_sets[right]))
        overlap = len(token_sets[left] & token_sets[right]) / max(1, small)
        score = 0.58 * title_j + 0.30 * overlap + min(0.12, hits * 0.025)
        if numbers[left] and numbers[left] & numbers[right]:
            score += 0.08
        if times[left] is not None and times[right] is not None:
            hours = abs(times[left] - times[right]) / 3600.0
            if hours <= 12:
                score += 0.05
            elif hours > 168:
                score -= 0.06
        if score >= 0.16:
            scored.append(_FastEdge(left, right, min(1.0, score)))

    scored.sort(key=lambda item: item.score, reverse=True)
    neighbor_count: Counter[int] = Counter()
    result: list[_FastEdge] = []
    for edge in scored:
        if neighbor_count[edge.left] >= _NEIGHBORS_PER_GROUP or neighbor_count[edge.right] >= _NEIGHBORS_PER_GROUP:
            continue
        result.append(edge)
        neighbor_count[edge.left] += 1
        neighbor_count[edge.right] += 1
        if len(result) >= _MAX_EDGES:
            break
    return result


def _records(groups: list[NewsGroup], *, max_chars: int) -> str:
    rows: list[str] = []
    per_group = max(90, min(210, max_chars // max(1, len(groups)) - 70))
    for group in groups:
        rows.append(
            f"ID={group.id} | ЗАГОЛОВОК={_clean_title(group.canonical_title, 170)} | "
            f"ТЕКСТ={_plain_group_text(group, per_group)}"
        )
    return "\n".join(rows)[:max_chars]


def build_global_duplicate_prompt(groups: list[NewsGroup], *, max_chars: int = _MAX_PROMPT_CHARS) -> str:
    if len(groups) < 2:
        return ""
    header = (
        "Визнач тільки повідомлення про ТУ САМУ конкретну подію. Схожа тема, країна, персона або організація не є дублікатом. "
        "Сумнівні пари пропускай. Один ID може бути лише в одному об'єднанні.\n"
        "Формат тільки: MERGE 12,18 | 91 | коротка причина. Якщо дублікатів немає: NONE. Без JSON і пояснень.\n"
        f"БЛОКИ ({len(groups)}):\n"
    )
    return (header + _records(groups, max_chars=max_chars - len(header)))[:max_chars]


def build_local_duplicate_prompt(groups: list[NewsGroup], *, max_chars: int = 3000) -> str:
    return build_global_duplicate_prompt(groups, max_chars=max_chars)


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
        if len(ids) >= 2 and confidence >= 55:
            reason = " ".join(str(match.group("reason") or "та сама подія").split())[:500]
            result.append(DuplicateCluster(tuple(ids), confidence, reason))
            used.update(ids)
    return result


def parse_duplicate_clusters(raw: str, valid_ids: set[int]) -> list[DuplicateCluster]:
    parsed = _parse_line_clusters(raw, valid_ids)
    if parsed is None:
        raise AIRouterError("AI повернув відповідь про дублікати у нерозпізнаному форматі.")
    return sorted(parsed, key=lambda item: (-item.confidence, item.group_ids))


def _fallback_clusters(groups: list[NewsGroup], edges: list[_FastEdge]) -> list[DuplicateCluster]:
    result: list[DuplicateCluster] = []
    used: set[int] = set()
    for edge in edges:
        left, right = groups[edge.left], groups[edge.right]
        if left.id in used or right.id in used:
            continue
        confidence = max(55, min(84, int(round(50 + edge.score * 42))))
        result.append(DuplicateCluster(
            (left.id, right.id),
            confidence,
            "Локальний кандидат за схожістю заголовка, тексту, чисел і часу; потрібне ручне підтвердження.",
        ))
        used.update((left.id, right.id))
    return result


def _ai_batch(groups: list[NewsGroup], edges: list[_FastEdge]) -> tuple[list[NewsGroup], set[int]]:
    indices: list[int] = []
    seen: set[int] = set()
    for edge in edges:
        for index in (edge.left, edge.right):
            if index not in seen:
                seen.add(index)
                indices.append(index)
                if len(indices) >= _MAX_AI_GROUPS:
                    chosen = [groups[i] for i in indices]
                    return chosen, {group.id for group in chosen}
    chosen = [groups[i] for i in indices]
    return chosen, {group.id for group in chosen}


def find_global_duplicate_clusters(
    groups: list[NewsGroup],
    *,
    feedback: Iterable[dict[str, object]] = (),
    graph_memory: str = "",
    cancel_event: threading.Event | None = None,
    progress: Callable[[str], None] | None = None,
    deadline_seconds: float = _GLOBAL_DEADLINE_SECONDS,
) -> list[DuplicateCluster]:
    del feedback, graph_memory
    global _LAST_DUPLICATE_SEARCH_MODE
    if len(groups) < 2:
        _LAST_DUPLICATE_SEARCH_MODE = "локальний prefilter"
        return []

    started = time.monotonic()
    deadline = started + max(8.0, min(90.0, float(deadline_seconds)))
    if progress:
        progress(f"Локальний prefilter: аналізую {len(groups)} блоків…")
    edges = _fast_candidate_edges(groups, deadline=deadline, cancel_event=cancel_event)
    if not edges:
        _LAST_DUPLICATE_SEARCH_MODE = "локальний prefilter"
        if progress:
            progress("Локальний prefilter не знайшов кандидатів на об'єднання.")
        return []

    local_all = _fallback_clusters(groups, edges)
    _check(cancel_event, deadline)
    batch, batch_ids = _ai_batch(groups, edges)
    if len(batch) < 2 or deadline - time.monotonic() < 8:
        _LAST_DUPLICATE_SEARCH_MODE = "локальні кандидати без AI"
        return local_all

    if progress:
        progress(f"AI-перевірка найсильніших кандидатів: {len(batch)} блоків; загальний ліміт 45 с.")
    prompt = build_global_duplicate_prompt(batch)
    valid_ids = set(batch_ids)

    def validate(raw: str) -> None:
        parse_duplicate_clusters(raw, valid_ids)

    remaining = max(8, int(deadline - time.monotonic()))
    try:
        routed = run_ai(
            prompt,
            validator=validate,
            max_output_tokens=_CLOUD_OUTPUT_TOKENS,
            local_prompt=build_local_duplicate_prompt(batch),
            local_max_output_tokens=_LOCAL_OUTPUT_TOKENS,
            local_timeout_seconds=_LOCAL_TIMEOUT_SECONDS,
            local_repair=False,
            cloud_timeout_seconds=_CLOUD_TIMEOUT_SECONDS,
            task_timeout_seconds=min(28, remaining),
            skip_providers={"codex"},
            suppress_provider_on_quota=True,
        )
        ai_clusters = parse_duplicate_clusters(routed.text, valid_ids)
        remainder_edges = [
            edge for edge in edges
            if not ({groups[edge.left].id, groups[edge.right].id} <= batch_ids)
        ]
        remainder = _fallback_clusters(groups, remainder_edges)
        _LAST_DUPLICATE_SEARCH_MODE = "AI Router + локальні кандидати" if remainder else "AI Router"
        return _select_non_overlapping([*ai_clusters, *remainder])
    except (AIRouterError, DuplicateSearchCancelled):
        _LAST_DUPLICATE_SEARCH_MODE = "локальні кандидати без AI"
        if progress:
            progress("AI не вклався у швидкий контур; показую локальні кандидати для ручної перевірки.")
        return local_all
