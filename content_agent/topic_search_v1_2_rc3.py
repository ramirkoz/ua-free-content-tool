from __future__ import annotations

from typing import Mapping, Sequence

from .editorial_memory_v1_2_rc3 import hybrid_similarity
from .i18n import normalize_language


def _relevant_feedback(anchor_text: str, feedback: Sequence[Mapping[str, object]], decision: str, limit: int = 4) -> list[Mapping[str, object]]:
    scored: list[tuple[float, Mapping[str, object]]] = []
    for row in feedback:
        if str(row.get("decision") or "").strip().lower() != decision:
            continue
        left = str(row.get("anchor_text") or "")
        right = str(row.get("candidate_text") or "")
        if not left or not right:
            continue
        score = max(hybrid_similarity(anchor_text, left), hybrid_similarity(anchor_text, right))
        if score >= 0.07:
            scored.append((score, row))
    scored.sort(key=lambda item: -item[0])
    return [row for _score, row in scored[:limit]]


def build_topic_prompt_rc3(
    anchor_title: str,
    anchor_text: str,
    candidates: Sequence[Mapping[str, object]],
    *,
    feedback: Sequence[Mapping[str, object]] = (),
    language: str = "uk",
) -> str:
    language = normalize_language(language)
    candidate_lines: list[str] = []
    for row in candidates:
        group_id = int(row.get("group_id") or row.get("id") or 0)
        title = " ".join(str(row.get("canonical_title") or row.get("title") or "").split())[:220]
        text = " ".join(str(row.get("combined_text") or row.get("text") or "").split())[:520]
        candidate_lines.append(f"ID {group_id}\nTITLE: {title}\nTEXT: {text}")

    positives = _relevant_feedback(anchor_text, feedback, "merged")
    negatives = _relevant_feedback(anchor_text, feedback, "not_related")
    learned: list[str] = []
    for label, rows in (("MERGED", positives), ("NOT_RELATED", negatives)):
        for row in rows:
            left = " ".join(str(row.get("anchor_text") or "").split())[:260]
            right = " ".join(str(row.get("candidate_text") or "").split())[:260]
            learned.append(f"{label}: {left} || {right}")
    learned_block = "\n".join(learned) if learned else "none"
    candidates_block = "\n\n".join(candidate_lines)

    protocol = "ID|SCORE|same_event/related/other|short reason"
    if language == "en":
        return f"""
You are deciding which collected news blocks describe the SAME concrete event as
the anchor. Topic similarity alone is not enough. Match actors, action, place,
time window, object, numbers and event identity. Different developments involving
the same country/person are NOT the same event.

Learned editor decisions are examples, not facts for the current story. MERGED is
a positive relation; NOT_RELATED is an explicit negative relation. Use only the
examples relevant to the anchor.

ANCHOR TITLE: {anchor_title}
ANCHOR: {anchor_text[:1800]}

RELEVANT LEARNED DECISIONS:
{learned_block}

CANDIDATES:
{candidates_block}

Return ONLY one line per candidate in this exact protocol:
{protocol}
SCORE is 0-100 confidence that the candidate is the same concrete event.
""".strip()

    return f"""
Визнач, які зібрані блоки описують ТУ САМУ КОНКРЕТНУ ПОДІЮ, що й опорний блок.
Схожої теми недостатньо. Зістав учасників, дію, місце, часовий проміжок, об'єкт,
числа та ідентичність події. Різні події за участю тієї самої країни чи особи НЕ
об'єднуй.

Попередні рішення редактора є лише прикладами зв'язків, а не фактами нової
новини. MERGED означає позитивний приклад, NOT_RELATED означає явно відхилений
зв'язок. Враховуй лише релевантні приклади.

ОПОРНИЙ ЗАГОЛОВОК: {anchor_title}
ОПОРНИЙ ТЕКСТ: {anchor_text[:1800]}

РЕЛЕВАНТНІ ПОПЕРЕДНІ РІШЕННЯ:
{learned_block}

КАНДИДАТИ:
{candidates_block}

Поверни ТІЛЬКИ по одному рядку на кандидата в точному форматі:
{protocol}
SCORE = впевненість 0-100, що це та сама конкретна подія.
""".strip()
