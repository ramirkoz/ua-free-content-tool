from __future__ import annotations

import re
from typing import Iterable, Mapping, Sequence

from .editorial_memory import EditorialExample, TopicCandidate, tokens
from .i18n import normalize_language

_WORD = re.compile(r"[0-9A-Za-zА-Яа-яІіЇїЄєҐґ'’-]{3,}")
_NUMBER = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?(?:%|\+)?(?!\w)")
_ENTITY = re.compile(r"\b[А-ЯІЇЄҐA-Z][А-Яа-яІіЇїЄєҐґA-Za-z'’-]{3,}\b")


def _stems(value: str) -> set[str]:
    result: set[str] = set()
    for token in tokens(value):
        if any(char.isdigit() for char in token):
            result.add(token)
        elif len(token) >= 8:
            result.add(token[:6])
        elif len(token) >= 6:
            result.add(token[:5])
        else:
            result.add(token)
    return result


def _ngrams(value: str, size: int = 4) -> set[str]:
    words = [match.group(0).lower().replace("’", "'") for match in _WORD.finditer(str(value or ""))]
    grams: set[str] = set()
    for word in words:
        if len(word) < size:
            grams.add(word)
            continue
        grams.update(word[index:index + size] for index in range(len(word) - size + 1))
    return grams


def _entities(value: str) -> set[str]:
    return {match.group(0).lower().replace("’", "'") for match in _ENTITY.finditer(str(value or ""))}


def _numbers(value: str) -> set[str]:
    return {match.group(0).replace(",", ".") for match in _NUMBER.finditer(str(value or ""))}


def _overlap_score(left: set[str], right: set[str]) -> tuple[float, float]:
    if not left or not right:
        return 0.0, 0.0
    common = left & right
    return (
        len(common) / max(1, len(left | right)),
        len(common) / max(1, min(len(left), len(right))),
    )


def hybrid_similarity(left: str, right: str) -> float:
    """Deterministic 0..1 similarity for inflected short news and learned retrieval."""

    left_tokens, right_tokens = tokens(left), tokens(right)
    token_j, token_c = _overlap_score(left_tokens, right_tokens)
    stem_j, stem_c = _overlap_score(_stems(left), _stems(right))
    gram_j, gram_c = _overlap_score(_ngrams(left), _ngrams(right))
    entity_j, entity_c = _overlap_score(_entities(left), _entities(right))
    number_j, number_c = _overlap_score(_numbers(left), _numbers(right))

    lexical = 0.42 * token_j + 0.58 * token_c
    morphology = 0.35 * stem_j + 0.65 * stem_c
    chars = 0.45 * gram_j + 0.55 * gram_c
    entities = max(entity_j, entity_c)
    numbers = max(number_j, number_c)

    score = 0.30 * lexical + 0.28 * morphology + 0.20 * chars
    if _entities(left) and _entities(right):
        score += 0.14 * entities
    if _numbers(left) and _numbers(right):
        score += 0.08 * numbers

    # Very short alerts often share only two or three decisive words. Containment
    # matters more than Jaccard there because one side can contain a long update.
    smaller = min(len(left_tokens), len(right_tokens))
    if 1 <= smaller <= 5:
        score = max(score, 0.72 * token_c + 0.28 * stem_c)
    return max(0.0, min(1.0, score))


def rank_editorial_examples_rc3(
    query_text: str,
    examples: Iterable[Mapping[str, object]],
    *,
    limit: int = 3,
    minimum_score: float = 0.055,
) -> list[EditorialExample]:
    ranked: list[EditorialExample] = []
    for row in examples:
        source_text = str(row.get("source_text") or "")
        final_text = str(row.get("final_text") or "")
        if not source_text or not final_text:
            continue
        score = hybrid_similarity(query_text, source_text)
        if score < minimum_score:
            continue
        ranked.append(
            EditorialExample(
                id=int(row.get("id") or 0),
                source_text=source_text,
                ai_draft_text=str(row.get("ai_draft_text") or ""),
                final_text=final_text,
                headline=str(row.get("headline") or ""),
                language=normalize_language(str(row.get("language") or "uk")),
                similarity=score,
            )
        )
    ranked.sort(key=lambda item: (-item.similarity, -item.id))
    return ranked[:max(0, int(limit))]


def feedback_relevance(anchor_text: str, candidate_text: str, row: Mapping[str, object]) -> float:
    left = str(row.get("anchor_text") or "")
    right = str(row.get("candidate_text") or "")
    if not left or not right:
        return 0.0
    direct = min(hybrid_similarity(anchor_text, left), hybrid_similarity(candidate_text, right))
    reverse = min(hybrid_similarity(anchor_text, right), hybrid_similarity(candidate_text, left))
    return max(direct, reverse)


def _learned_adjustment(anchor_text: str, candidate_text: str, feedback: Sequence[Mapping[str, object]]) -> tuple[float, float, float]:
    positive: list[float] = []
    negative: list[float] = []
    for row in feedback:
        relevance = feedback_relevance(anchor_text, candidate_text, row)
        if relevance < 0.08:
            continue
        decision = str(row.get("decision") or "").strip().lower()
        if decision == "merged":
            positive.append(relevance)
        elif decision == "not_related":
            negative.append(relevance)
    positive.sort(reverse=True)
    negative.sort(reverse=True)
    pos = sum(positive[:3]) / max(1, len(positive[:3])) if positive else 0.0
    neg = sum(negative[:3]) / max(1, len(negative[:3])) if negative else 0.0
    return 0.22 * pos - 0.30 * neg, pos, neg


def rank_topic_candidates_rc3(
    anchor_text: str,
    candidates: Iterable[Mapping[str, object]],
    *,
    feedback: Sequence[Mapping[str, object]] = (),
    limit: int = 24,
    language: str = "uk",
) -> list[TopicCandidate]:
    language = normalize_language(language)
    ranked: list[TopicCandidate] = []
    for row in candidates:
        group_id = int(row.get("group_id") or row.get("id") or 0)
        text = str(row.get("text") or row.get("combined_text") or "")
        title = str(row.get("canonical_title") or row.get("title") or "")
        if not group_id or not text:
            continue
        body_score = hybrid_similarity(anchor_text, text)
        title_score = hybrid_similarity(anchor_text, title) if title else 0.0
        base = max(body_score, 0.72 * body_score + 0.28 * title_score)
        learned, positive, negative = _learned_adjustment(anchor_text, text, feedback)
        score = max(0.0, min(1.0, base + learned))
        if score < 0.035:
            continue
        if negative >= 0.45 and negative > positive * 1.15:
            reason = "схоже на раніше відхилений зв'язок" if language == "uk" else "similar to a previously rejected relation"
        elif positive >= 0.28:
            reason = "підсилено вашими попередніми об’єднаннями" if language == "uk" else "boosted by previous manual merges"
        elif title_score > body_score + 0.08:
            reason = "сильний збіг події в заголовку" if language == "uk" else "strong event match in title"
        else:
            reason = "збіг події, назв, чисел або учасників" if language == "uk" else "event, entity, number or participant match"
        ranked.append(TopicCandidate(group_id=group_id, score=score, reason=reason))
    ranked.sort(key=lambda item: (-item.score, item.group_id))
    # The legacy UI asked for 12. RC3 deliberately gives Ollama a slightly wider
    # shortlist so learned recall is not destroyed before semantic verification.
    effective_limit = max(int(limit), 18) if int(limit) > 0 else 0
    return ranked[:effective_limit]
