from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_section(path: str, pattern: str, replacement: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S | re.M)
    if count != 1:
        raise SystemExit(f"Could not repair generated section in {path}: count={count}")
    target.write_text(updated, encoding="utf-8", newline="\n")


replace_section(
    "content_agent/editorial_memory.py",
    r"def format_examples_for_prompt\(.*?\n\ndef exclusion_similarity",
    r'''def format_examples_for_prompt(
    examples: Sequence[EditorialExample],
    *,
    language: str = "uk",
) -> str:
    if not examples:
        return ""
    language = normalize_language(language)
    blocks: list[str] = []
    for index, item in enumerate(examples, start=1):
        source = " ".join(item.source_text.split())[:900]
        final = item.final_text.strip()[:900]
        if language == "en":
            blocks.append(
                f"EXAMPLE {index} (similarity {item.similarity:.2f})\n"
                f"SOURCE FACTS: {source}\n"
                f"EDITOR'S FINAL TEXT: {final}"
            )
        else:
            blocks.append(
                f"ПРИКЛАД {index} (схожість {item.similarity:.2f})\n"
                f"ВИХІДНІ ФАКТИ: {source}\n"
                f"ФІНАЛЬНИЙ ТЕКСТ РЕДАКТОРА: {final}"
            )
    return "\n\n".join(blocks)


def exclusion_similarity''',
)

replace_section(
    "content_agent/topic_search.py",
    r"def build_topic_prompt\(.*?\n\ndef parse_topic_matches",
    r'''def build_topic_prompt(
    anchor_title: str,
    anchor_text: str,
    candidates: Iterable[Mapping[str, object]],
    *,
    feedback: Iterable[Mapping[str, object]] = (),
    language: str = "uk",
) -> str:
    language = normalize_language(language)
    blocks: list[str] = []
    for row in candidates:
        group_id = int(row.get("group_id") or row.get("id") or 0)
        title = str(row.get("title") or "")
        text = " ".join(str(row.get("text") or "").split())[:750]
        if group_id:
            if language == "en":
                blocks.append(f"ID {group_id}\nHEADLINE: {title}\nTEXT: {text}")
            else:
                blocks.append(f"ID {group_id}\nЗАГОЛОВОК: {title}\nТЕКСТ: {text}")
    candidate_block = "\n\n---\n\n".join(blocks)
    learned_blocks: list[str] = []
    for index, row in enumerate(feedback, start=1):
        if index > 6:
            break
        if str(row.get("decision") or "merged") != "merged":
            continue
        left = " ".join(str(row.get("anchor_text") or "").split())[:550]
        right = " ".join(str(row.get("candidate_text") or "").split())[:550]
        if language == "en":
            learned_blocks.append(
                f"LEARNING EXAMPLE {index}: the editor merged these materials as one event.\n"
                f"A: {left}\nB: {right}"
            )
        else:
            learned_blocks.append(
                f"НАВЧАЛЬНИЙ ПРИКЛАД {index}: редактор об'єднав ці матеріали як одну подію.\n"
                f"A: {left}\nB: {right}"
            )
    if language == "en":
        learned_block = "\n\n".join(learned_blocks) or "There are no learning examples yet."
        return f"""
You help an editor find reports about one specific news event.
Do not merge or rewrite anything. Classify each candidate as:
- same_event: the same event, a direct update, consequence, or reaction to it;
- related: a close topic but a different event;
- other: unrelated to this event.

The 0–100 score is confidence that the candidate is same_event. Do not inflate
the score because of generic shared words. Consider date, place, participants,
numbers, object, and causal connection. Previous manual merges are examples of
grouping logic only; never copy facts from them.

PREVIOUS MANUAL MERGES:
{learned_block}

Return ONLY one line per candidate:
ID|SCORE|same_event/related/other|short reason

ANCHOR STORY:
HEADLINE: {anchor_title}
TEXT: {" ".join(anchor_text.split())[:1800]}

CANDIDATES:
{candidate_block}
""".strip()
    learned_block = "\n\n".join(learned_blocks) or "Навчальних прикладів ще немає."
    return f"""
Ти допомагаєш редактору знайти матеріали про одну конкретну новинну подію.
Не об'єднуй самостійно і не переписуй тексти. Для кожного кандидата визнач:
- same_event: та сама подія, уточнення, наслідки або реакція саме на неї;
- related: близька тема, але інша подія;
- other: не стосується цієї події.

Оцінка 0–100 має показувати впевненість, що це same_event. Не завищуй оцінку
лише через однакові загальні слова. Враховуй дату, місце, учасників, числа,
об'єкт і причинно-наслідковий зв'язок. Попередні ручні об'єднання є лише
прикладами логіки групування; не перенось із них факти.

ПОПЕРЕДНІ РУЧНІ ОБ'ЄДНАННЯ:
{learned_block}

Поверни ТІЛЬКИ по одному рядку на кандидата:
ID|ОЦІНКА|same_event/related/other|коротка причина

ОПОРНА НОВИНА:
ЗАГОЛОВОК: {anchor_title}
ТЕКСТ: {" ".join(anchor_text.split())[:1800]}

КАНДИДАТИ:
{candidate_block}
""".strip()


def parse_topic_matches''',
)

Path(__file__).unlink()
print("generated bilingual prompt sources repaired")
