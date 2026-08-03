from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from .editorial_memory import TopicCandidate

_LINE_RE = re.compile(
    r"(?im)^\s*(?P<id>\d+)\s*[|;]\s*(?P<score>\d{1,3})\s*[|;]\s*"
    r"(?P<label>same_event|related|other|та_сама_подія|пов'язано|інше)\s*[|;]\s*(?P<reason>.+?)\s*$"
)


@dataclass(frozen=True, slots=True)
class OllamaTopicMatch:
    group_id: int
    score: int
    label: str
    reason: str


def build_topic_prompt(
    anchor_title: str,
    anchor_text: str,
    candidates: Iterable[Mapping[str, object]],
    *,
    feedback: Iterable[Mapping[str, object]] = (),
) -> str:
    blocks: list[str] = []
    for row in candidates:
        group_id = int(row.get("group_id") or row.get("id") or 0)
        title = str(row.get("title") or "")
        text = " ".join(str(row.get("text") or "").split())[:750]
        if group_id:
            blocks.append(f"ID {group_id}\nЗАГОЛОВОК: {title}\nТЕКСТ: {text}")
    candidate_block = "\n\n---\n\n".join(blocks)
    learned_blocks: list[str] = []
    for index, row in enumerate(feedback, start=1):
        if index > 6:
            break
        if str(row.get("decision") or "merged") != "merged":
            continue
        learned_blocks.append(
            f"НАВЧАЛЬНИЙ ПРИКЛАД {index}: редактор об'єднав ці матеріали як одну подію.\n"
            f"A: {' '.join(str(row.get('anchor_text') or '').split())[:550]}\n"
            f"B: {' '.join(str(row.get('candidate_text') or '').split())[:550]}"
        )
    learned_block = "\n\n".join(learned_blocks) or "Навчальних прикладів ще немає."
    return f"""
Ти допомагаєш редактору знайти матеріали про одну конкретну новинну подію.
Не об'єднуй самостійно і не переписуй тексти. Для кожного кандидата визнач:
- same_event: та сама подія, уточнення, наслідки або реакція саме на неї;
- related: близька тема, але інша подія;
- other: не стосується цієї події.

Оцінка 0–100 має показувати впевненість, що це same_event. Не завищуй оцінку
лише через однакові слова «Запоріжжя», «атака», «влада» або ім'я посадовця.
Враховуй дату, місце, учасників, числа, об'єкт і причинно-наслідковий зв'язок.
Нижче також наведено попередні ручні об'єднання редактора. Використовуй їх
як приклади логіки групування, але не підтягуй із них факти до поточної теми.

ПОПЕРЕДНІ РУЧНІ ОБ'ЄДНАННЯ:
{learned_block}

Поверни ТІЛЬКИ по одному рядку на кандидата у форматі:
ID|ОЦІНКА|same_event/related/other|коротка причина

ОПОРНА НОВИНА:
ЗАГОЛОВОК: {anchor_title}
ТЕКСТ: {" ".join(anchor_text.split())[:1800]}

КАНДИДАТИ:
{candidate_block}
""".strip()


def parse_topic_matches(text: str) -> dict[int, OllamaTopicMatch]:
    result: dict[int, OllamaTopicMatch] = {}
    for match in _LINE_RE.finditer(str(text or "")):
        group_id = int(match.group("id"))
        score = max(0, min(100, int(match.group("score"))))
        raw_label = match.group("label").lower()
        label = {
            "та_сама_подія": "same_event",
            "пов'язано": "related",
            "інше": "other",
        }.get(raw_label, raw_label)
        result[group_id] = OllamaTopicMatch(
            group_id=group_id,
            score=score,
            label=label,
            reason=match.group("reason").strip(),
        )
    return result


def merge_local_and_ollama(
    local: Iterable[TopicCandidate],
    ollama: Mapping[int, OllamaTopicMatch],
    *,
    minimum_score: int = 45,
) -> list[OllamaTopicMatch]:
    merged: list[OllamaTopicMatch] = []
    local_map = {item.group_id: item for item in local}
    for group_id, local_item in local_map.items():
        model = ollama.get(group_id)
        if model is None:
            fallback_score = int(round(local_item.score * 100))
            if fallback_score >= minimum_score:
                merged.append(
                    OllamaTopicMatch(group_id, fallback_score, "same_event", local_item.reason)
                )
            continue
        # Ollama decides event identity; local/manual history breaks ties and
        # protects against a weak small-model response.
        learned_bonus = int(round(max(0.0, local_item.score - 0.35) * 20))
        final_score = min(100, model.score + learned_bonus)
        if model.label == "same_event" and final_score >= minimum_score:
            merged.append(
                OllamaTopicMatch(group_id, final_score, model.label, model.reason)
            )
    merged.sort(key=lambda item: (-item.score, item.group_id))
    return merged
