from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable

from .ai_router_v1_2_1 import AIRouterError, run_ai
from .models import NewsGroup

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class DuplicateCluster:
    group_ids: tuple[int, ...]
    confidence: int
    reason: str


def _plain_group_text(group: NewsGroup, limit: int) -> str:
    parts: list[str] = []
    for article in group.articles:
        text = " ".join(str(article.raw_text or "").split())
        if text:
            parts.append(text)
    value = " ".join(parts)
    return value[:limit]


def _feedback_text(feedback: Iterable[dict[str, object]], limit: int = 60) -> str:
    rows: list[str] = []
    for item in list(feedback)[-limit:]:
        decision = str(item.get("decision") or "").strip()
        left = " ".join(str(item.get("anchor_text") or "").split())[:260]
        right = " ".join(str(item.get("candidate_text") or "").split())[:260]
        if not decision or not left or not right:
            continue
        label = "ОБ'ЄДНАНО" if decision == "merged" else "НЕ ПОВ'ЯЗАНО"
        rows.append(f"{label}: A={left} | B={right}")
    return "\n".join(rows)


def build_global_duplicate_prompt(
    groups: list[NewsGroup],
    *,
    feedback: Iterable[dict[str, object]] = (),
    graph_memory: str = "",
) -> str:
    if len(groups) < 2:
        return ""
    # Every new group must be represented. Shrink excerpts as the inbox grows so
    # one global pass does not silently drop old/new candidates to fit context.
    excerpt_limit = max(140, min(700, 90_000 // max(1, len(groups))))
    records: list[str] = []
    for group in groups:
        records.append(
            " | ".join(
                (
                    f"ID={group.id}",
                    f"ДЖЕРЕЛ={group.source_count}",
                    f"ЧАС={group.last_published_at or group.updated_at or 'невідомо'}",
                    f"ЗАГОЛОВОК={group.canonical_title}",
                    f"ТЕКСТ={_plain_group_text(group, excerpt_limit)}",
                )
            )
        )
    feedback_block = _feedback_text(feedback)
    memory = ""
    if feedback_block:
        memory += "\n\nПОПЕРЕДНІ РІШЕННЯ РЕДАКТОРА:\n" + feedback_block
    if graph_memory:
        memory += (
            "\n\nЛОКАЛЬНА РЕДАКЦІЙНА ПАМ'ЯТЬ:\n"
            + graph_memory
            + "\nПам'ять є лише прикладом правил редактора, не джерелом фактів про поточні новини."
        )
    return f"""
Проаналізуй ВСІ наведені нові редакційні блоки між собою та знайди групи, які варто об'єднати як дублікати або повідомлення про ту саму конкретну подію.

ПРАВИЛА:
1. Один ID може входити максимум в один запропонований кластер.
2. У кластері має бути мінімум 2 ID.
3. Об'єднуй лише ту саму подію, той самий конкретний факт або пряме уточнення тієї самої події.
4. Одна країна, людина, організація, війна, тема чи рубрика НЕ є достатньою підставою для об'єднання.
5. Різні події, що сталися з тим самим об'єктом у різний час, залишай окремими.
6. Якщо впевненість нижча за 55%, не пропонуй кластер.
7. Блок із ДЖЕРЕЛ>1 вже є об'єднаним блоком, але його все одно порівнюй з усіма іншими.
8. Не вигадуй зв'язків. Краще пропустити сумнівний дублікат, ніж об'єднати різні події.

Поверни РІВНО JSON без markdown і без пояснення до/після:
{{"clusters":[{{"group_ids":[12,18],"confidence":91,"reason":"коротка конкретна причина"}}]}}
{memory}

УСІ НОВІ БЛОКИ ({len(groups)}):
""".strip() + "\n" + "\n".join(records)


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


def find_global_duplicate_clusters(
    groups: list[NewsGroup],
    *,
    feedback: Iterable[dict[str, object]] = (),
    graph_memory: str = "",
) -> list[DuplicateCluster]:
    if len(groups) < 2:
        return []
    prompt = build_global_duplicate_prompt(groups, feedback=feedback, graph_memory=graph_memory)
    valid_ids = {group.id for group in groups}

    def validate(raw: str) -> None:
        parse_duplicate_clusters(raw, valid_ids)

    routed = run_ai(prompt, validator=validate)
    return parse_duplicate_clusters(routed.text, valid_ids)
