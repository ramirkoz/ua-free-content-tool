from __future__ import annotations

import re
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Callable, Iterable

from .ai_router_v1_2_2 import AIRouterError, run_ai
from .global_duplicates_v1_2_2_rc6 import (
    DuplicateSearchCancelled,
    _FastEdge,
    _ai_batch,
    _fallback_clusters,
    build_global_duplicate_prompt,
    build_local_duplicate_prompt,
    parse_duplicate_clusters,
)
from .global_duplicates_v1_3_rc6 import DuplicateCluster, _clean_title, _plain_group_text, _select_non_overlapping, _tokens
from .models import NewsGroup

_CLOUD_OUTPUT_TOKENS = 360
_LOCAL_OUTPUT_TOKENS = 180
_CLOUD_TIMEOUT_SECONDS = 6
_LOCAL_TIMEOUT_SECONDS = 12
_GLOBAL_DEADLINE_SECONDS = 45
_MAX_EDGES = 160
_NEIGHBORS_PER_GROUP = 4
_MAX_BLOCK_TOKENS = 10
_MAX_PAIR_CANDIDATES = 12_000
_BODY_CHARS = 420
_LAST_DUPLICATE_SEARCH_MODE = "локальний prefilter RC7"


def last_duplicate_search_label() -> str:
    return _LAST_DUPLICATE_SEARCH_MODE


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise DuplicateSearchCancelled("Пошук об'єднань скасовано користувачем.")


def _parse_time(group: NewsGroup) -> float | None:
    raw = group.last_published_at or group.updated_at or group.created_at
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _title_bigrams(tokens: list[str]) -> list[str]:
    return [f"{left}\x1f{right}" for left, right in zip(tokens, tokens[1:]) if left != right]


def _fast_candidate_edges(
    groups: list[NewsGroup],
    *,
    deadline: float,
    cancel_event: threading.Event | None = None,
) -> list[_FastEdge]:
    """Strictly bounded candidate generation for large, noisy inboxes.

    RC6 could still create a very large pair counter when many medium-frequency
    body tokens shared 20-40 groups. RC7 blocks mainly on titles, rare adjacent
    title bigrams and only a tiny body supplement, then caps the pair set.
    """
    del deadline  # The prefilter itself is bounded; the global deadline is for AI/network work.
    n = len(groups)
    if n < 2:
        return []

    title_lists: list[list[str]] = []
    title_sets: list[set[str]] = []
    body_sets: list[set[str]] = []
    token_sets: list[set[str]] = []
    numbers: list[set[str]] = []
    times: list[float | None] = []
    title_df: Counter[str] = Counter()
    body_df: Counter[str] = Counter()
    bigram_df: Counter[str] = Counter()
    normalized_titles: defaultdict[str, list[int]] = defaultdict(list)

    for index, group in enumerate(groups):
        if index % 64 == 0:
            _check_cancel(cancel_event)
        title = _clean_title(group.canonical_title, 260)
        title_tokens = _tokens(title)
        title_set = set(title_tokens)
        body_set = set(_tokens(_plain_group_text(group, _BODY_CHARS)))
        all_tokens = title_set | body_set
        bigrams = set(_title_bigrams(title_tokens))

        title_lists.append(title_tokens)
        title_sets.append(title_set)
        body_sets.append(body_set)
        token_sets.append(all_tokens)
        numbers.append({token for token in all_tokens if token.isdigit() and len(token) >= 2})
        times.append(_parse_time(group))
        title_df.update(title_set)
        body_df.update(body_set)
        bigram_df.update(bigrams)

        title_key = " ".join(title_tokens)[:180]
        if title_key:
            normalized_titles[title_key].append(index)

    max_title_posting = max(8, min(28, n // 24 + 8))
    max_body_posting = max(6, min(18, n // 40 + 6))
    postings: defaultdict[str, list[int]] = defaultdict(list)

    for index, title_tokens in enumerate(title_lists):
        _check_cancel(cancel_event)
        selected: list[str] = []

        bigrams = sorted(
            {
                value
                for value in _title_bigrams(title_tokens)
                if 1 < bigram_df[value] <= 12
            },
            key=lambda value: (bigram_df[value], -len(value), value),
        )[:4]
        selected.extend(f"b:{value}" for value in bigrams)

        title_candidates = sorted(
            (
                token
                for token in title_sets[index]
                if 1 < title_df[token] <= max_title_posting
            ),
            key=lambda token: (title_df[token], -len(token), token),
        )[:6]
        selected.extend(f"t:{token}" for token in title_candidates)

        if len(selected) < _MAX_BLOCK_TOKENS:
            body_candidates = sorted(
                (
                    token
                    for token in body_sets[index] - title_sets[index]
                    if 1 < body_df[token] <= max_body_posting
                ),
                key=lambda token: (body_df[token], -len(token), token),
            )[: _MAX_BLOCK_TOKENS - len(selected)]
            selected.extend(f"x:{token}" for token in body_candidates)

        for key in selected[:_MAX_BLOCK_TOKENS]:
            postings[key].append(index)

    pair_hits: Counter[tuple[int, int]] = Counter()
    posting_rows = sorted(postings.items(), key=lambda item: (len(item[1]), item[0]))
    for pos, (key, members) in enumerate(posting_rows):
        if pos % 64 == 0:
            _check_cancel(cancel_event)
        if len(members) < 2:
            continue
        weight = 3 if key.startswith("b:") else 1
        for left_pos in range(len(members)):
            left = members[left_pos]
            for right_pos in range(left_pos + 1, len(members)):
                right = members[right_pos]
                pair_hits[(left, right)] += weight
                if len(pair_hits) >= _MAX_PAIR_CANDIDATES:
                    break
            if len(pair_hits) >= _MAX_PAIR_CANDIDATES:
                break
        if len(pair_hits) >= _MAX_PAIR_CANDIDATES:
            break

    for members in normalized_titles.values():
        if 1 < len(members) <= 12:
            for left_pos in range(len(members)):
                for right_pos in range(left_pos + 1, len(members)):
                    pair_hits[(members[left_pos], members[right_pos])] += 5

    scored: list[_FastEdge] = []
    ranked_pairs = sorted(pair_hits.items(), key=lambda item: (-item[1], item[0]))
    for pos, ((left, right), hits) in enumerate(ranked_pairs):
        if pos % 128 == 0:
            _check_cancel(cancel_event)
        title_union = title_sets[left] | title_sets[right]
        title_jaccard = len(title_sets[left] & title_sets[right]) / max(1, len(title_union))
        small = min(len(token_sets[left]), len(token_sets[right]))
        overlap = len(token_sets[left] & token_sets[right]) / max(1, small)
        score = 0.60 * title_jaccard + 0.28 * overlap + min(0.14, hits * 0.03)

        if numbers[left] and numbers[left] & numbers[right]:
            score += 0.08
        if times[left] is not None and times[right] is not None:
            hours = abs(times[left] - times[right]) / 3600.0
            if hours <= 12:
                score += 0.05
            elif hours > 168:
                score -= 0.06
        if score >= 0.15:
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
        _LAST_DUPLICATE_SEARCH_MODE = "локальний prefilter RC7"
        return []

    started = time.monotonic()
    deadline = started + max(8.0, min(90.0, float(deadline_seconds)))
    if progress:
        progress(f"Швидкий локальний prefilter RC7: аналізую {len(groups)} блоків…")

    edges = _fast_candidate_edges(groups, deadline=deadline, cancel_event=cancel_event)
    _check_cancel(cancel_event)
    if not edges:
        _LAST_DUPLICATE_SEARCH_MODE = "локальний prefilter RC7"
        if progress:
            progress("Локальний prefilter не знайшов достатньо схожих пар.")
        return []

    local_all = _fallback_clusters(groups, edges)
    batch, batch_ids = _ai_batch(groups, edges)
    remaining_seconds = deadline - time.monotonic()
    if len(batch) < 2 or remaining_seconds < 8:
        _LAST_DUPLICATE_SEARCH_MODE = "локальні кандидати RC7 без AI"
        return local_all

    if progress:
        progress(f"AI-перевірка {len(batch)} найсильніших кандидатів; локальні кандидати не будуть втрачені.")
    prompt = build_global_duplicate_prompt(batch)
    valid_ids = set(batch_ids)

    def validate(raw: str) -> None:
        parse_duplicate_clusters(raw, valid_ids)

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
            task_timeout_seconds=min(28, max(8, int(remaining_seconds))),
            skip_providers={"codex"},
            suppress_provider_on_quota=True,
        )
        _check_cancel(cancel_event)
        ai_clusters = parse_duplicate_clusters(routed.text, valid_ids)
        # AI may confirm or add confidence, but it no longer vetoes a strong
        # deterministic review candidate. Nothing is merged automatically.
        combined = _select_non_overlapping([*ai_clusters, *local_all])
        _LAST_DUPLICATE_SEARCH_MODE = "AI Router + локальні кандидати RC7"
        return combined
    except DuplicateSearchCancelled:
        raise
    except AIRouterError:
        _check_cancel(cancel_event)
        _LAST_DUPLICATE_SEARCH_MODE = "локальні кандидати RC7 без AI"
        if progress:
            progress("AI недоступний або не вклався; показую локальні кандидати для ручної перевірки.")
        return local_all
