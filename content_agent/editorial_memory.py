from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

_WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яІіЇїЄєҐґ'’-]{3,}")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")

# Compact list on purpose: names, places, numbers and event words must remain
# searchable. This is a retrieval helper, not a language model.
_STOPWORDS = {
    "аби", "але", "або", "без", "був", "була", "були", "буде", "від", "вона",
    "вони", "воно", "для", "до", "його", "її", "їх", "над", "під", "після",
    "про", "при", "та", "так", "також", "той", "ця", "цей", "це", "через",
    "що", "щоб", "яка", "який", "які", "уже", "вже", "між", "свої", "свою",
    "заявив", "заявила", "повідомив", "повідомила", "повідомляє", "йдеться",
}


@dataclass(frozen=True, slots=True)
class EditorialExample:
    id: int
    source_text: str
    ai_draft_text: str
    final_text: str
    headline: str = ""
    similarity: float = 0.0


@dataclass(frozen=True, slots=True)
class TopicCandidate:
    group_id: int
    score: float
    reason: str


def normalize_text(value: str) -> str:
    return " ".join(str(value or "").lower().replace("’", "'").split())


def tokens(value: str) -> set[str]:
    result: set[str] = set()
    for match in _WORD_RE.finditer(normalize_text(value)):
        word = match.group(0).strip("-'–")
        if len(word) >= 3 and word not in _STOPWORDS:
            result.add(word)
    return result


def weighted_similarity(left: str, right: str) -> float:
    """Deterministic lexical/entity score in the 0..1 range.

    Numbers and capitalized/name-like tokens receive a small boost because they
    separate concrete news events much better than generic topic vocabulary.
    """

    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens & right_tokens
    union = left_tokens | right_tokens
    jaccard = len(overlap) / max(1, len(union))
    containment = len(overlap) / max(1, min(len(left_tokens), len(right_tokens)))

    digit_overlap = {item for item in overlap if any(char.isdigit() for char in item)}
    proper_overlap = {
        item
        for item in overlap
        if len(item) >= 5 and item not in _STOPWORDS
    }
    boost = min(0.18, 0.04 * len(digit_overlap) + 0.012 * len(proper_overlap))
    return min(1.0, 0.58 * jaccard + 0.42 * containment + boost)


def rank_editorial_examples(
    query_text: str,
    examples: Iterable[Mapping[str, object]],
    *,
    limit: int = 3,
    minimum_score: float = 0.08,
) -> list[EditorialExample]:
    ranked: list[EditorialExample] = []
    for row in examples:
        source_text = str(row.get("source_text") or "")
        final_text = str(row.get("final_text") or "")
        if not source_text or not final_text:
            continue
        score = weighted_similarity(query_text, source_text)
        if score < minimum_score:
            continue
        ranked.append(
            EditorialExample(
                id=int(row.get("id") or 0),
                source_text=source_text,
                ai_draft_text=str(row.get("ai_draft_text") or ""),
                final_text=final_text,
                headline=str(row.get("headline") or ""),
                similarity=score,
            )
        )
    ranked.sort(key=lambda item: (-item.similarity, -item.id))
    return ranked[: max(0, int(limit))]


def _feedback_boost(anchor_text: str, candidate_text: str, feedback: Sequence[Mapping[str, object]]) -> float:
    best = 0.0
    for row in feedback:
        decision = str(row.get("decision") or "merged")
        left = str(row.get("anchor_text") or "")
        right = str(row.get("candidate_text") or "")
        if not left or not right:
            continue
        direct = min(weighted_similarity(anchor_text, left), weighted_similarity(candidate_text, right))
        reverse = min(weighted_similarity(anchor_text, right), weighted_similarity(candidate_text, left))
        match = max(direct, reverse)
        if decision == "merged":
            best = max(best, 0.24 * match)
        elif decision == "not_related":
            best = min(best, -0.24 * match)
    return best


def rank_topic_candidates(
    anchor_text: str,
    candidates: Iterable[Mapping[str, object]],
    *,
    feedback: Sequence[Mapping[str, object]] = (),
    limit: int = 24,
) -> list[TopicCandidate]:
    ranked: list[TopicCandidate] = []
    for row in candidates:
        group_id = int(row.get("group_id") or row.get("id") or 0)
        candidate_text = str(row.get("text") or row.get("combined_text") or "")
        if not group_id or not candidate_text:
            continue
        base = weighted_similarity(anchor_text, candidate_text)
        learned = _feedback_boost(anchor_text, candidate_text, feedback)
        score = max(0.0, min(1.0, base + learned))
        if score < 0.045:
            continue
        reason = "збіг фактів, назв або учасників"
        if learned > 0.03:
            reason = "схоже на ваші попередні ручні об’єднання"
        ranked.append(TopicCandidate(group_id=group_id, score=score, reason=reason))
    ranked.sort(key=lambda item: (-item.score, item.group_id))
    return ranked[: max(0, int(limit))]


def split_threads_chain(text: str, limit: int = 500) -> list[str]:
    """Split one editorial message into at most sentence-safe Threads parts.

    No text is silently discarded. A single overlong sentence is cut on a word
    boundary, because the API limit is physical rather than philosophical.
    """

    remaining = str(text or "").strip()
    if not remaining:
        return [""]
    parts: list[str] = []
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        cut = remaining.rfind("\n\n", 0, limit + 1)
        if cut < limit // 3:
            sentence_positions = [match.end() for match in re.finditer(r"[.!?…](?:\s+|$)", remaining[: limit + 1])]
            cut = sentence_positions[-1] if sentence_positions else -1
        if cut < limit // 3:
            cut = remaining.rfind(" ", 0, limit + 1)
        if cut < limit // 3:
            cut = limit
        chunk = remaining[:cut].strip()
        if not chunk:
            chunk = remaining[:limit]
            cut = len(chunk)
        parts.append(chunk)
        remaining = remaining[cut:].strip()
    return parts


def format_examples_for_prompt(examples: Sequence[EditorialExample]) -> str:
    if not examples:
        return ""
    blocks: list[str] = []
    for index, item in enumerate(examples, start=1):
        source = " ".join(item.source_text.split())[:900]
        final = item.final_text.strip()[:900]
        blocks.append(
            f"ПРИКЛАД {index} (схожість {item.similarity:.2f})\n"
            f"ВИХІДНІ ФАКТИ: {source}\n"
            f"ФІНАЛЬНИЙ ТЕКСТ РЕДАКТОРА: {final}"
        )
    return "\n\n".join(blocks)


def exclusion_similarity(candidate_text: str, excluded_text: str) -> tuple[float, int]:
    """Return a conservative local match score for permanent inbox exclusions.

    Exclusion memory must work during background collection without waking Ollama.
    The score combines the existing entity-aware similarity with an explicit count
    of shared meaningful tokens so one generic word cannot suppress a whole topic.
    """

    left = tokens(candidate_text)
    right = tokens(excluded_text)

    # Ukrainian and Russian news feeds inflect the same topic words heavily
    # ("відстеження" / "відстежувати", "трекерами" / "трекерів").
    # A short deterministic stem is enough for exclusion memory and avoids
    # waking Ollama during every five-minute background collection.
    def stems(values: set[str]) -> set[str]:
        return {value[:6] if len(value) >= 7 else value for value in values}

    left_stems = stems(left)
    right_stems = stems(right)
    overlap = left_stems & right_stems
    union = left_stems | right_stems
    shared = len(overlap)
    stem_jaccard = shared / max(1, len(union))
    stem_containment = shared / max(1, min(len(left_stems), len(right_stems)))
    stem_score = 0.55 * stem_jaccard + 0.45 * stem_containment
    return max(weighted_similarity(candidate_text, excluded_text), stem_score), shared


def matches_content_exclusion(
    candidate_text: str,
    excluded_text: str,
    *,
    strong_threshold: float = 0.34,
    contextual_threshold: float = 0.24,
) -> bool:
    """Decide whether a newly collected item matches an editor exclusion example.

    A high semantic/entity score is sufficient on its own. A softer match needs at
    least four shared meaningful tokens, which protects against broad false matches
    such as every article containing only «Україна» and «влада».
    """

    score, shared = exclusion_similarity(candidate_text, excluded_text)
    return score >= strong_threshold or (score >= contextual_threshold and shared >= 4)
