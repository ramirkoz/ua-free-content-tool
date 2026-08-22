from __future__ import annotations

import logging
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
    build_global_duplicate_prompt,
    build_local_duplicate_prompt,
    parse_duplicate_clusters,
)
from .global_duplicates_v1_3_rc6 import DuplicateCluster, _clean_title, _plain_group_text, _select_non_overlapping, _tokens
from .models import NewsGroup

logger = logging.getLogger("content_agent.duplicates")

_CLOUD_OUTPUT_TOKENS = 360
_LOCAL_OUTPUT_TOKENS = 180
_CLOUD_TIMEOUT_SECONDS = 8
_LOCAL_TIMEOUT_SECONDS = 10
_GLOBAL_DEADLINE_SECONDS = 65
_MAX_EDGES = 480
_NEIGHBORS_PER_GROUP = 8
_MAX_BLOCK_TOKENS = 14
_MAX_PAIR_CANDIDATES = 30_000
_BODY_CHARS = 900
_MAX_AI_GROUPS = 12
_MAX_AI_BATCHES = 6
_LAST_DUPLICATE_SEARCH_MODE = "локальний prefilter"


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
    """Bounded near-linear candidate generation using real article text.

    The UI loads hydrated NewsGroup objects before calling this function. The
    prefilter therefore compares title + article body + numbers + time instead
    of the old title-only shells returned by Database.list_groups().
    """
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
    token_df: Counter[str] = Counter()
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
        token_df.update(all_tokens)
        bigram_df.update(bigrams)

        title_key = " ".join(title_tokens)[:180]
        if title_key:
            normalized_titles[title_key].append(index)

    max_title_posting = max(10, min(36, n // 20 + 10))
    max_body_posting = max(8, min(24, n // 32 + 8))
    postings: defaultdict[str, list[int]] = defaultdict(list)

    for index, title_tokens in enumerate(title_lists):
        _check_cancel(cancel_event)
        if time.monotonic() >= deadline:
            break
        selected: list[str] = []

        bigrams = sorted(
            {value for value in _title_bigrams(title_tokens) if 1 < bigram_df[value] <= 16},
            key=lambda value: (bigram_df[value], -len(value), value),
        )[:5]
        selected.extend(f"b:{value}" for value in bigrams)

        title_candidates = sorted(
            (token for token in title_sets[index] if 1 < title_df[token] <= max_title_posting),
            key=lambda token: (title_df[token], -len(token), token),
        )[:7]
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
            if time.monotonic() >= deadline:
                break
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
        if 1 < len(members) <= 16:
            for left_pos in range(len(members)):
                for right_pos in range(left_pos + 1, len(members)):
                    pair_hits[(members[left_pos], members[right_pos])] += 5

    scored: list[_FastEdge] = []
    ranked_pairs = sorted(pair_hits.items(), key=lambda item: (-item[1], item[0]))
    for pos, ((left, right), hits) in enumerate(ranked_pairs):
        if pos % 128 == 0:
            _check_cancel(cancel_event)
            if time.monotonic() >= deadline:
                break
        title_union = title_sets[left] | title_sets[right]
        title_jaccard = len(title_sets[left] & title_sets[right]) / max(1, len(title_union))
        small = min(len(token_sets[left]), len(token_sets[right]))
        overlap = len(token_sets[left] & token_sets[right]) / max(1, small)
        shared_tokens = token_sets[left] & token_sets[right]
        rare_limit = max(4, min(18, int(round(n * 0.02))))
        shared_rare = {
            token
            for token in shared_tokens
            if len(token) >= 4 and token_df[token] <= rare_limit
        }
        shared_numbers = numbers[left] & numbers[right]
        shared_specific_numbers = {
            token
            for token in shared_numbers
            if (len(token) >= 3 or int(token) > 31)
            and token_df[token] <= max(10, rare_limit * 2)
        }
        exact_title = bool(title_lists[left]) and title_lists[left] == title_lists[right]

        # Global merge must be high precision. Generic topical overlap is not an
        # event identity signal: require at least one specific shared anchor
        # (rare entity/model/place token, meaningful number, or exact title).
        # This prevents broad topic-clusters such as multiple NASA/Swift stories
        # or unrelated strike reports from being proposed as one event.
        if not (exact_title or shared_rare or shared_specific_numbers):
            continue

        score = 0.52 * title_jaccard + 0.29 * overlap + min(0.15, hits * 0.03)
        if exact_title:
            score += 0.12
        if shared_rare:
            score += min(0.14, 0.05 + 0.025 * len(shared_rare))
        if shared_specific_numbers:
            score += 0.08

        # Conflicting factual numbers are useful negative evidence. Keep dates
        # like 21 out of this rule so a common day-of-month cannot falsely make
        # two otherwise different reports look identical.
        if numbers[left] and numbers[right] and not shared_specific_numbers:
            left_specific = {v for v in numbers[left] if len(v) >= 3 or int(v) > 31}
            right_specific = {v for v in numbers[right] if len(v) >= 3 or int(v) > 31}
            if left_specific and right_specific:
                score -= 0.14
        if times[left] is not None and times[right] is not None:
            hours = abs(times[left] - times[right]) / 3600.0
            if hours <= 12:
                score += 0.06
            elif hours <= 48:
                score += 0.025
            elif hours > 168:
                score -= 0.08
        if score >= 0.14:
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


def _local_review_clusters(groups: list[NewsGroup], edges: list[_FastEdge]) -> list[DuplicateCluster]:
    """Build review candidates without letting AI availability veto the search.

    Strong edges may form small components; weaker edges stay pairs. Everything
    still requires manual confirmation in the existing dialog.
    """
    if not edges:
        return []

    parent = list(range(len(groups)))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    for edge in edges:
        if edge.score >= 0.52:
            union(edge.left, edge.right)

    components: defaultdict[int, list[int]] = defaultdict(list)
    for index in range(len(groups)):
        components[find(index)].append(index)

    result: list[DuplicateCluster] = []
    used: set[int] = set()
    edge_scores = {(min(e.left, e.right), max(e.left, e.right)): e.score for e in edges}
    for indices in components.values():
        if len(indices) < 2:
            continue
        # Avoid giant topic-clusters. A real same-event group can be large, but a
        # local lexical component >8 is more safely reviewed in smaller chunks.
        for start in range(0, len(indices), 8):
            chunk = indices[start : start + 8]
            if len(chunk) < 2:
                continue
            ids = tuple(groups[index].id for index in chunk)
            scores = [
                edge_scores.get((min(a, b), max(a, b)), 0.0)
                for pos, a in enumerate(chunk)
                for b in chunk[pos + 1 :]
            ]
            top = max(scores or [0.38])
            confidence = max(60, min(86, int(round(54 + top * 38))))
            result.append(
                DuplicateCluster(
                    ids,
                    confidence,
                    "Сильний локальний кандидат за збігом заголовків, тексту, чисел і часу; потрібне ручне підтвердження.",
                )
            )
            used.update(ids)

    for edge in edges:
        left_id = groups[edge.left].id
        right_id = groups[edge.right].id
        if left_id in used or right_id in used or edge.score < 0.22:
            continue
        confidence = max(55, min(78, int(round(50 + edge.score * 38))))
        result.append(
            DuplicateCluster(
                (left_id, right_id),
                confidence,
                "Локальний кандидат за схожістю заголовка, тексту, чисел і часу; потрібне ручне підтвердження.",
            )
        )
        used.update((left_id, right_id))

    return sorted(result, key=lambda item: (-item.confidence, item.group_ids))


def _build_ai_batches(groups: list[NewsGroup], edges: list[_FastEdge]) -> list[list[NewsGroup]]:
    batches: list[list[NewsGroup]] = []
    remaining = list(edges)
    while remaining and len(batches) < _MAX_AI_BATCHES:
        nodes: list[int] = []
        seen: set[int] = set()
        consumed: set[int] = set()
        for edge_index, edge in enumerate(remaining):
            needed = [index for index in (edge.left, edge.right) if index not in seen]
            if len(seen) + len(needed) > _MAX_AI_GROUPS:
                continue
            for index in needed:
                seen.add(index)
                nodes.append(index)
            consumed.add(edge_index)
            if len(seen) >= _MAX_AI_GROUPS:
                break
        if len(nodes) < 2:
            break
        batches.append([groups[index] for index in nodes])
        remaining = [edge for index, edge in enumerate(remaining) if index not in consumed]
    return batches


def find_global_duplicate_clusters(
    groups: list[NewsGroup],
    *,
    feedback: Iterable[dict[str, object]] = (),
    graph_memory: str = "",
    cancel_event: threading.Event | None = None,
    progress: Callable[[str], None] | None = None,
    deadline_seconds: float = _GLOBAL_DEADLINE_SECONDS,
    hydrate_groups: Callable[[Iterable[int]], list[NewsGroup]] | None = None,
) -> list[DuplicateCluster]:
    del feedback, graph_memory
    global _LAST_DUPLICATE_SEARCH_MODE
    if len(groups) < 2:
        _LAST_DUPLICATE_SEARCH_MODE = "локальний prefilter"
        return []

    started = time.monotonic()
    deadline = started + max(15.0, min(90.0, float(deadline_seconds)))
    article_count = sum(len(group.articles) for group in groups)
    logger.info("Global duplicate search start groups=%d articles=%d", len(groups), article_count)
    if progress:
        progress(f"Аналізую {len(groups)} блоків / {article_count} текстів локальним prefilter…")

    edges = _fast_candidate_edges(groups, deadline=deadline, cancel_event=cancel_event)
    _check_cancel(cancel_event)
    logger.info("Global duplicate prefilter complete groups=%d edges=%d elapsed=%.2fs", len(groups), len(edges), time.monotonic() - started)
    if not edges:
        _LAST_DUPLICATE_SEARCH_MODE = "локальний prefilter"
        if progress:
            progress("Локальний prefilter не знайшов достатньо схожих пар.")
        return []

    # Stage 2: hydrate only groups that survived the cheap preview prefilter.
    # This keeps the scan responsive even when the inbox contains many thousands
    # of groups or some groups themselves contain dozens of source articles.
    if hydrate_groups is not None and time.monotonic() < deadline - 4:
        candidate_indices = sorted({index for edge in edges for index in (edge.left, edge.right)})
        candidate_ids = [groups[index].id for index in candidate_indices]
        if progress:
            progress(f"Уточнюю {len(candidate_ids)} кандидатів повними текстами…")
        hydrated = hydrate_groups(candidate_ids)
        hydrated_by_id = {group.id: group for group in hydrated}
        hydrated_groups = [hydrated_by_id[group_id] for group_id in candidate_ids if group_id in hydrated_by_id]
        if len(hydrated_groups) >= 2:
            groups = hydrated_groups
            edges = _fast_candidate_edges(groups, deadline=deadline, cancel_event=cancel_event)
            logger.info(
                "Global duplicate hydration refine groups=%d edges=%d elapsed=%.2fs",
                len(groups), len(edges), time.monotonic() - started,
            )
            if not edges:
                _LAST_DUPLICATE_SEARCH_MODE = "локальний prefilter"
                return []

    local_all = _local_review_clusters(groups, edges)
    proposals: list[DuplicateCluster] = []
    batches = _build_ai_batches(groups, edges)
    ai_successes = 0

    for batch_index, batch in enumerate(batches, start=1):
        _check_cancel(cancel_event)
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds < 7:
            break
        if progress:
            progress(
                f"AI-перевірка кандидатів {batch_index}/{len(batches)} · {len(batch)} блоків; "
                "локальні кандидати вже збережені."
            )
        valid_ids = {group.id for group in batch}

        def validate(raw: str, ids: set[int] = valid_ids) -> None:
            parse_duplicate_clusters(raw, ids)

        try:
            routed = run_ai(
                build_global_duplicate_prompt(batch),
                validator=validate,
                max_output_tokens=_CLOUD_OUTPUT_TOKENS,
                local_prompt=build_local_duplicate_prompt(batch),
                local_max_output_tokens=_LOCAL_OUTPUT_TOKENS,
                local_timeout_seconds=_LOCAL_TIMEOUT_SECONDS,
                local_repair=False,
                cloud_timeout_seconds=_CLOUD_TIMEOUT_SECONDS,
                task_timeout_seconds=min(16, max(7, int(remaining_seconds))),
                suppress_provider_on_quota=True,
                cancel_event=cancel_event,
            )
            parsed = parse_duplicate_clusters(routed.text, valid_ids)
            proposals.extend(parsed)
            ai_successes += 1
            logger.info(
                "Global duplicate AI batch=%d/%d provider=%s model=%s clusters=%d",
                batch_index, len(batches), routed.provider, routed.model, len(parsed),
            )
        except DuplicateSearchCancelled:
            raise
        except AIRouterError as exc:
            logger.warning("Global duplicate AI batch=%d failed: %s", batch_index, str(exc)[:500])
            # Do not spend the rest of the deadline repeatedly proving that every
            # provider is unavailable. The deterministic candidates remain useful.
            if "Немає доступного AI-провайдера" in str(exc):
                break
            continue

    combined = _select_non_overlapping([*proposals, *local_all])
    if ai_successes:
        _LAST_DUPLICATE_SEARCH_MODE = "AI Router + локальний prefilter"
    else:
        _LAST_DUPLICATE_SEARCH_MODE = "локальний prefilter без AI"
    logger.info(
        "Global duplicate search done groups=%d edges=%d local=%d ai=%d result=%d elapsed=%.2fs",
        len(groups), len(edges), len(local_all), len(proposals), len(combined), time.monotonic() - started,
    )
    if progress:
        progress(f"Готово: {len(combined)} кандидатів на об'єднання.")
    return combined
