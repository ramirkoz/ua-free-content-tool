from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .ai_router_v1_2_2 import AIRouterError, run_ai
from .models import NewsGroup

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[^\W_]{2,}", re.UNICODE)
_MAX_BATCH_GROUPS = 20
_MAX_BATCH_PROMPT_CHARS = 8_000
_NEIGHBORS_PER_GROUP = 4
_DUPLICATE_OUTPUT_TOKENS = 900

# Lightweight stopword set for the languages that dominate the inbox. The
# prefilter only proposes candidates; AI still makes the actual merge decision.
_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "have", "has", "was", "were", "are", "not", "but", "into", "about", "after", "before", "over", "under", "new", "news",
    "і", "й", "та", "але", "або", "для", "про", "від", "до", "на", "у", "в", "з", "із", "за", "що", "це", "як", "не", "після", "перед", "новий", "нова", "нове", "нові",
    "и", "а", "но", "или", "для", "про", "от", "до", "на", "в", "с", "из", "за", "что", "это", "как", "не", "после", "перед", "новый", "новая", "новое", "новые",
}


@dataclass(frozen=True, slots=True)
class DuplicateCluster:
    group_ids: tuple[int, ...]
    confidence: int
    reason: str


@dataclass(frozen=True, slots=True)
class _CandidateEdge:
    left: int
    right: int
    score: float


def _plain_group_text(group: NewsGroup, limit: int) -> str:
    parts: list[str] = []
    for article in group.articles:
        text = " ".join(str(article.raw_text or "").split())
        if text:
            parts.append(text)
    value = " ".join(parts)
    return value[:limit]


def _feedback_text(feedback: Iterable[dict[str, object]], limit: int = 12) -> str:
    rows: list[str] = []
    for item in list(feedback)[-limit:]:
        decision = str(item.get("decision") or "").strip()
        left = " ".join(str(item.get("anchor_text") or "").split())[:180]
        right = " ".join(str(item.get("candidate_text") or "").split())[:180]
        if not decision or not left or not right:
            continue
        label = "ОБ'ЄДНАНО" if decision == "merged" else "НЕ ПОВ'ЯЗАНО"
        rows.append(f"{label}: A={left} | B={right}")
    return "\n".join(rows)


def _clean_title(value: str, limit: int = 220) -> str:
    return " ".join(str(value or "").split())[:limit]


def build_global_duplicate_prompt(
    groups: list[NewsGroup],
    *,
    feedback: Iterable[dict[str, object]] = (),
    graph_memory: str = "",
    max_chars: int = _MAX_BATCH_PROMPT_CHARS,
) -> str:
    if len(groups) < 2:
        return ""

    feedback_block = _feedback_text(feedback)
    memory = ""
    if feedback_block:
        memory += "\n\nПОПЕРЕДНІ РІШЕННЯ РЕДАКТОРА:\n" + feedback_block
    if graph_memory:
        compact_graph = " ".join(str(graph_memory).split())[:1200]
        if compact_graph:
            memory += (
                "\n\nЛОКАЛЬНА РЕДАКЦІЙНА ПАМ'ЯТЬ:\n"
                + compact_graph
                + "\nПам'ять є лише прикладом правил редактора, не джерелом фактів про поточні новини."
            )

    header = f"""
Проаналізуй ВСІ наведені редакційні блоки між собою та знайди групи, які варто об'єднати як дублікати або повідомлення про ту саму конкретну подію.

ПРАВИЛА:
1. Один ID може входити максимум в один запропонований кластер.
2. У кластері має бути мінімум 2 ID.
3. Об'єднуй лише ту саму подію, той самий конкретний факт або пряме уточнення тієї самої події.
4. Одна країна, людина, організація, війна, тема чи рубрика НЕ є достатньою підставою для об'єднання.
5. Різні події, що сталися з тим самим об'єктом у різний час, залишай окремими.
6. Якщо впевненість нижча за 55%, не пропонуй кластер.
7. Блок із ДЖЕРЕЛ>1 вже є об'єднаним блоком, але його все одно порівнюй з іншими.
8. Не вигадуй зв'язків. Краще пропустити сумнівний дублікат, ніж об'єднати різні події.

Поверни РІВНО JSON без markdown і без пояснення до/після:
{{"clusters":[{{"group_ids":[12,18],"confidence":91,"reason":"коротка конкретна причина"}}]}}
{memory}

БЛОКИ В ЦЬОМУ ПАКЕТІ ({len(groups)}):
""".strip()

    # Reserve room for metadata and keep the full prompt comfortably below the
    # 8K-TPM class of free providers. Cyrillic tokenization is less char-efficient
    # than English, hence the deliberately conservative character budget.
    fixed = len(header) + 80 * len(groups) + 1
    available = max(120 * len(groups), max_chars - fixed)
    excerpt_limit = max(100, min(420, available // max(1, len(groups)) - 80))

    def records_for(limit: int) -> list[str]:
        rows: list[str] = []
        for group in groups:
            rows.append(
                " | ".join(
                    (
                        f"ID={group.id}",
                        f"ДЖЕРЕЛ={group.source_count}",
                        f"ЧАС={group.last_published_at or group.updated_at or 'невідомо'}",
                        f"ЗАГОЛОВОК={_clean_title(group.canonical_title)}",
                        f"ТЕКСТ={_plain_group_text(group, limit)}",
                    )
                )
            )
        return rows

    records = records_for(excerpt_limit)
    prompt = header + "\n" + "\n".join(records)
    if len(prompt) > max_chars:
        # Rebuild rather than slicing the JSON instructions or a record in half.
        overflow = len(prompt) - max_chars
        shrink_each = math.ceil(overflow / max(1, len(groups))) + 16
        excerpt_limit = max(70, excerpt_limit - shrink_each)
        records = records_for(excerpt_limit)
        prompt = header + "\n" + "\n".join(records)
    return prompt


def parse_duplicate_clusters(raw: str, valid_ids: set[int]) -> list[DuplicateCluster]:
    cleaned = _CODE_FENCE.sub("", str(raw or "").strip()).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AIRouterError("AI повернув глобальний пошук дублікатів не у валідному JSON.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("clusters"), list):
        raise AIRouterError("AI повернув неправильну структуру глобального пошуку дублікатів.")
    result: list[DuplicateCluster] = []
    used: set[int] = set()
    for row in payload["clusters"]:
        if not isinstance(row, dict):
            continue
        ids: list[int] = []
        for value in row.get("group_ids", []):
            try:
                group_id = int(value)
            except (TypeError, ValueError):
                continue
            if group_id in valid_ids and group_id not in ids and group_id not in used:
                ids.append(group_id)
        try:
            confidence = max(0, min(100, int(row.get("confidence") or 0)))
        except (TypeError, ValueError):
            confidence = 0
        if len(ids) < 2 or confidence < 55:
            continue
        reason = " ".join(str(row.get("reason") or "").split())[:500]
        cluster = DuplicateCluster(tuple(ids), confidence, reason)
        result.append(cluster)
        used.update(ids)
    return sorted(result, key=lambda item: (-item.confidence, item.group_ids))


def _tokens(value: str) -> list[str]:
    result: list[str] = []
    for token in _TOKEN_RE.findall(str(value or "").casefold()):
        if token in _STOPWORDS:
            continue
        if len(token) < 3 and not token.isdigit():
            continue
        result.append(token)
    return result


def _group_vector_text(group: NewsGroup) -> tuple[list[str], set[str], set[str]]:
    title_tokens = _tokens(_clean_title(group.canonical_title, 300))
    text_tokens = _tokens(_plain_group_text(group, 1200))
    numbers = {token for token in title_tokens + text_tokens if token.isdigit() and len(token) >= 2}
    return title_tokens + text_tokens, set(title_tokens), numbers


def _parse_time(group: NewsGroup) -> float | None:
    raw = group.last_published_at or group.updated_at or group.created_at
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _candidate_edges(groups: list[NewsGroup]) -> list[_CandidateEdge]:
    if len(groups) < 2:
        return []
    docs: list[list[str]] = []
    titles: list[set[str]] = []
    numbers: list[set[str]] = []
    times: list[float | None] = []
    df: Counter[str] = Counter()
    for group in groups:
        doc, title, nums = _group_vector_text(group)
        docs.append(doc)
        titles.append(title)
        numbers.append(nums)
        times.append(_parse_time(group))
        df.update(set(doc))

    n = len(groups)
    vectors: list[dict[str, float]] = []
    norms: list[float] = []
    for doc in docs:
        counts = Counter(doc)
        vector: dict[str, float] = {}
        for token, count in counts.items():
            idf = math.log((n + 1) / (df[token] + 1)) + 1.0
            vector[token] = (1.0 + math.log(max(1, count))) * idf
        vectors.append(vector)
        norms.append(math.sqrt(sum(value * value for value in vector.values())) or 1.0)

    all_scores: list[list[tuple[float, int]]] = [[] for _ in groups]
    for left in range(n):
        for right in range(left + 1, n):
            small, large = (vectors[left], vectors[right]) if len(vectors[left]) <= len(vectors[right]) else (vectors[right], vectors[left])
            dot = sum(value * large.get(token, 0.0) for token, value in small.items())
            cosine = dot / (norms[left] * norms[right])
            union = titles[left] | titles[right]
            title_jaccard = (len(titles[left] & titles[right]) / len(union)) if union else 0.0
            number_bonus = 0.08 if numbers[left] and (numbers[left] & numbers[right]) else 0.0
            time_bonus = 0.0
            if times[left] is not None and times[right] is not None:
                delta_hours = abs(times[left] - times[right]) / 3600.0
                if delta_hours <= 24:
                    time_bonus = 0.05
                elif delta_hours <= 72:
                    time_bonus = 0.025
            shared_tokens = set(docs[left]) & set(docs[right])
            rare_limit = max(4, math.ceil(n * 0.08))
            shared_rare = any(df[token] <= rare_limit for token in shared_tokens)
            shared_numbers = bool(numbers[left] and (numbers[left] & numbers[right]))
            lexical_evidence = max(cosine, title_jaccard)
            if lexical_evidence < 0.03:
                time_bonus = 0.0
            score = 0.72 * cosine + 0.20 * title_jaccard + number_bonus + time_bonus
            eligible = shared_rare or (shared_numbers and cosine >= 0.08) or (title_jaccard >= 0.40 and cosine >= 0.08)
            if not eligible:
                score = 0.0
            all_scores[left].append((score, right))
            all_scores[right].append((score, left))

    edge_map: dict[tuple[int, int], float] = {}
    for index, candidates in enumerate(all_scores):
        # Only semantic/lexical candidates go to AI. Same-event reports normally
        # share names, places, products, numbers or distinctive terms; unrelated
        # contemporaneous news must not burn cloud quota merely because it is new.
        selected = [item for item in sorted(candidates, key=lambda item: item[0], reverse=True) if item[0] >= 0.11]
        for score, other in selected[:_NEIGHBORS_PER_GROUP]:
            left, right = sorted((index, other))
            edge_map[(left, right)] = max(score, edge_map.get((left, right), -1.0))
    return [
        _CandidateEdge(left, right, score)
        for (left, right), score in sorted(edge_map.items(), key=lambda item: item[1], reverse=True)
    ]


def build_global_duplicate_batches(groups: list[NewsGroup]) -> list[list[NewsGroup]]:
    """Build small overlapping candidate batches instead of one giant prompt."""
    if len(groups) < 2:
        return []
    if len(groups) <= _MAX_BATCH_GROUPS:
        return [list(groups)]

    edges = _candidate_edges(groups)
    remaining = {(edge.left, edge.right): edge.score for edge in edges}
    batches: list[list[NewsGroup]] = []
    while remaining:
        seed = max(remaining, key=remaining.get)
        nodes: set[int] = set(seed)
        while len(nodes) < _MAX_BATCH_GROUPS:
            touching = [
                (score, left, right)
                for (left, right), score in remaining.items()
                if (left in nodes) ^ (right in nodes)
            ]
            if not touching:
                break
            _score, left, right = max(touching)
            nodes.add(right if left in nodes else left)
        ordered = sorted(nodes)
        batches.append([groups[index] for index in ordered])
        # Every candidate edge fully represented in this batch is now covered.
        for edge in list(remaining):
            if edge[0] in nodes and edge[1] in nodes:
                remaining.pop(edge, None)

    return batches


def _select_non_overlapping(clusters: Iterable[DuplicateCluster]) -> list[DuplicateCluster]:
    result: list[DuplicateCluster] = []
    used: set[int] = set()
    for cluster in sorted(clusters, key=lambda item: (-item.confidence, item.group_ids)):
        if used.intersection(cluster.group_ids):
            continue
        result.append(cluster)
        used.update(cluster.group_ids)
    return result


def find_global_duplicate_clusters(
    groups: list[NewsGroup],
    *,
    feedback: Iterable[dict[str, object]] = (),
    graph_memory: str = "",
) -> list[DuplicateCluster]:
    if len(groups) < 2:
        return []

    batches = build_global_duplicate_batches(groups)
    proposals: list[DuplicateCluster] = []
    for batch in batches:
        prompt = build_global_duplicate_prompt(batch, feedback=feedback, graph_memory=graph_memory)
        valid_ids = {group.id for group in batch}

        def validate(raw: str, ids: set[int] = valid_ids) -> None:
            parse_duplicate_clusters(raw, ids)

        routed = run_ai(prompt, validator=validate, max_output_tokens=_DUPLICATE_OUTPUT_TOKENS)
        proposals.extend(parse_duplicate_clusters(routed.text, valid_ids))

    return _select_non_overlapping(proposals)
