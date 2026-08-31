from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .scheduling import KYIV


TOPIC_CATEGORIES = (
    "Війна",
    "Політика",
    "Суспільство",
    "Економіка",
    "Міжнародне",
    "Технології",
    "Наука",
    "Бізнес",
    "Культура",
    "Спорт",
    "Інше",
)

# The old classifier returned the first category whose substring happened to be
# present in the canonical headline. RC4 scores the whole merged event instead:
# canonical headline > source headlines > article bodies. Geography is kept out
# of the topic axis and emitted only as tags.
_TOPIC_RULES: dict[str, tuple[tuple[str, float], ...]] = {
    "Війна": (
        ("обстріл", 3.2), ("обстрел", 3.2), ("ракет", 3.0), ("missile", 3.0),
        ("дрон", 2.8), ("бпла", 2.8), ("шахед", 3.0), ("удар", 2.2),
        ("атака", 2.2), ("атакував", 2.4), ("атаковали", 2.4), ("зсу", 2.4),
        ("збройн", 2.2), ("військ", 1.8), ("военн", 1.8), ("фронт", 2.4),
        ("окуп", 2.5), ("бойов", 2.2), ("air strike", 3.0), ("drone strike", 3.2),
        ("war", 1.7), ("ппо", 2.6), ("зрк", 2.6), ("фаб-", 3.0),
        ("fpv", 2.8), ("терорист", 1.8), ("террорист", 1.8),
    ),
    "Політика": (
        ("президент", 2.2), ("парламент", 2.5), ("верховн", 2.2), ("кабмін", 2.5),
        ("уряд", 2.1), ("government", 2.1), ("міністр", 1.8), ("министр", 1.8),
        ("депутат", 2.0), ("вибор", 2.6), ("election", 2.8), ("парті", 2.0),
        ("політик", 2.0), ("politic", 2.0), ("законопроєкт", 2.5),
        ("законопроект", 2.5), ("коаліц", 2.5), ("опозиці", 2.3),
    ),
    "Суспільство": (
        ("освіт", 2.5), ("школ", 2.6), ("універс", 2.5), ("учн", 2.0),
        ("студент", 2.0), ("поліц", 2.0), ("полици", 2.0), ("суд", 1.7),
        ("корупц", 2.4), ("злочин", 2.3), ("crime", 2.3), ("соціаль", 1.8),
        ("суспіль", 2.0), ("демограф", 2.4), ("населен", 1.8), ("медици", 1.6),
        ("лікар", 2.0), ("education", 2.5), ("court", 1.8), ("police", 2.1),
        ("society", 2.0), ("правоохорон", 2.2), ("громад", 1.3),
    ),
    "Економіка": (
        ("економ", 2.7), ("інфляц", 3.0), ("inflation", 3.0), ("ввп", 3.0),
        ("gdp", 3.0), ("бюджет", 2.6), ("нбу", 2.8), ("центробанк", 2.8),
        ("курс валют", 3.0), ("гривн", 2.0), ("рубл", 2.0), ("подат", 2.4),
        ("налог", 2.4), ("мит", 1.8), ("тариф", 2.3), ("tariff", 2.3),
        ("експорт", 2.2), ("імпорт", 2.2), ("export", 2.2), ("import", 2.2),
        ("ринок праці", 2.6), ("безроб", 2.5),
    ),
    "Міжнародне": (
        ("нато", 2.6), ("nato", 2.6), ("оон", 2.6), ("united nations", 2.6),
        ("євросоюз", 2.6), ("european union", 2.6), ("єс ", 1.8), ("g7", 2.4),
        ("g20", 2.4), ("дипломат", 2.3), ("саміт", 2.3), ("summit", 2.3),
        ("санкц", 2.3), ("посольств", 2.1), ("мирн переговор", 2.6),
        ("міжнарод", 2.0), ("международ", 2.0), ("foreign minister", 2.2),
    ),
    "Технології": (
        ("штучн", 2.5), ("нейромереж", 2.6), ("нейросет", 2.6), ("openai", 2.8),
        ("chatgpt", 2.8), ("anthropic", 2.8), ("gemini", 2.4), ("software", 2.2),
        ("кібер", 2.7), ("cyber", 2.7), ("хакер", 2.6), ("malware", 2.7),
        ("ransomware", 2.8), ("чип", 2.3), ("процесор", 2.3), ("gpu", 2.4),
        ("npu", 2.4), ("sdk", 2.3), ("api", 1.8), ("android", 2.1),
        ("ios", 2.1), ("windows", 2.0), ("meta ", 1.8), ("facebook", 1.7),
        ("instagram", 1.7), ("threads", 1.7), ("google", 1.5), ("apple", 1.5),
        ("microsoft", 1.5), ("технолог", 2.2), ("robot", 2.2), ("робот", 2.2),
        ("стартап", 1.7), ("data center", 2.2), ("дата-центр", 2.2),
    ),
    "Наука": (
        ("дослідж", 2.7), ("исследован", 2.7), ("research", 2.7), ("scientist", 2.6),
        ("вчен", 2.6), ("учен", 2.6), ("науков", 2.5), ("science", 2.5),
        ("космос", 2.7), ("space", 2.7), ("nasa", 3.0), ("esa", 2.6),
        ("астроном", 2.8), ("телескоп", 2.7), ("фізик", 2.5), ("physics", 2.5),
        ("біолог", 2.5), ("biology", 2.5), ("геном", 2.7), ("квант", 2.7),
        ("cern", 3.0), ("лаборатор", 2.1), ("експеримент", 2.2), ("experiment", 2.2),
    ),
    "Бізнес": (
        ("компан", 1.8), ("company", 1.8), ("бізнес", 2.4), ("business", 2.4),
        ("угод", 2.4), ("deal", 2.4), ("інвест", 2.5), ("investment", 2.5),
        ("funding", 2.7), ("виручк", 2.6), ("revenue", 2.6), ("прибут", 2.5),
        ("profit", 2.5), ("акці", 2.1), ("shares", 1.7), ("ipo", 2.8),
        ("придбал", 2.4), ("acquisition", 2.5), ("merger", 2.6),
    ),
    "Культура": (
        ("фільм", 2.6), ("film", 2.6), ("movie", 2.6), ("серіал", 2.6),
        ("series", 2.3), ("музик", 2.6), ("music", 2.6), ("альбом", 2.7),
        ("книг", 2.5), ("book", 2.3), ("театр", 2.6), ("мистец", 2.6),
        ("art ", 2.2), ("актор", 2.4), ("режисер", 2.5), ("director", 2.0),
        ("прем'єр", 1.9), ("premiere", 2.3),
    ),
    "Спорт": (
        ("футбол", 3.0), ("football", 3.0), ("баскет", 3.0), ("basketball", 3.0),
        ("теніс", 3.0), ("tennis", 3.0), ("олімпі", 3.0), ("olympic", 3.0),
        ("матч", 2.6), ("чемпіон", 2.8), ("champion", 2.8), ("турнір", 2.8),
        ("tournament", 2.8), ("boxing", 3.0), ("бокс", 2.7), ("спорт", 2.4),
    ),
}

_GEO_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Київ", ("київ", "києв", "киев", "kyiv", "kiev")),
    ("Київщина", ("київщ", "киевск")),
    ("Запоріжжя", ("запоріж", "запорож")),
    ("Дніпро", ("дніпр", "днепр")),
    ("Харків", ("харків", "харьков")),
    ("Одеса", ("одес",)),
    ("Львів", ("львів", "львов")),
    ("Донеччина", ("донеч", "донец")),
    ("Україна", ("україн", "украин", "ukrain")),
    ("Росія", ("росі", "росси", "russia")),
    ("США", ("сша", "united states", " usa ", "америк")),
    ("ЄС", ("євросоюз", "european union", " eu ")),
    ("Німеччина", ("німеч", "герман", "germany")),
    ("Франція", ("франц", "france")),
    ("Польща", ("польщ", "poland")),
    ("Китай", ("китай", "china")),
    ("Ізраїль", ("ізраїл", "израил", "israel")),
)

_TAG_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("БПЛА", ("бпла", "дрон", "drone", "fpv", "шахед")),
    ("ракетні удари", ("ракет", "missile")),
    ("ППО", ("ппо", "air defense", "зрк")),
    ("освіта", ("освіт", "школ", "education", "універс")),
    ("корупція", ("корупц", "corruption")),
    ("AI", ("штучн", "openai", "chatgpt", "anthropic", "gemini", "нейромереж")),
    ("кібербезпека", ("кібер", "cyber", "хакер", "malware", "ransomware")),
    ("соцмережі", ("facebook", "instagram", "threads", "tiktok", "social media")),
    ("космос", ("космос", "space", "nasa", "esa", "телескоп")),
    ("енергетика", ("енерг", "electric", "power grid", "електро")),
    ("інфраструктура", ("інфраструкт", "логістич", "аеропорт", "порт ", "залізниц")),
    ("медицина", ("медицин", "лікар", "health", "disease", "пацієн")),
    ("санкції", ("санкц", "sanction")),
)


@dataclass(slots=True, frozen=True)
class TopicDecision:
    topic: str
    tags: tuple[str, ...]
    confidence: int
    fingerprint: str
    manual: bool = False


def _normalized(value: str) -> str:
    text = str(value or "").casefold().replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return f" {text.strip()} "


def _contains(text: str, marker: str) -> bool:
    return marker.casefold() in text


def fingerprint_context(context: dict[str, object]) -> str:
    title = str(context.get("canonical_title") or "")
    source_titles = context.get("article_titles") if isinstance(context.get("article_titles"), list) else []
    body = str(context.get("body") or "")
    compact = "\n".join([title, *[str(value) for value in source_titles], body[:16000]])
    return hashlib.sha256(compact.encode("utf-8", errors="ignore")).hexdigest()[:24]


def classify_topic_context(context: dict[str, object]) -> TopicDecision:
    canonical = _normalized(str(context.get("canonical_title") or ""))
    source_titles = [
        _normalized(str(value))
        for value in (context.get("article_titles") if isinstance(context.get("article_titles"), list) else [])
        if str(value or "").strip()
    ]
    body = _normalized(str(context.get("body") or "")[:20000])
    sections: list[tuple[str, float]] = [(canonical, 6.0)]
    sections.extend((title, 3.8) for title in source_titles[:12])
    if body.strip():
        sections.append((body, 1.0))

    scores: dict[str, float] = {topic: 0.0 for topic in _TOPIC_RULES}
    for topic, rules in _TOPIC_RULES.items():
        total = 0.0
        for text, section_weight in sections:
            for marker, marker_weight in rules:
                if _contains(text, marker):
                    total += section_weight * marker_weight
        scores[topic] = total

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_topic, best_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else 0.0

    # A weak accidental hit is less useful than an explicit "Інше". Strong and
    # repeated evidence across several source headlines quickly clears this bar.
    if best_score < 8.0:
        topic = "Інше"
        confidence = max(35, min(55, int(best_score * 5)))
    else:
        topic = best_topic
        separation = max(0.0, best_score - second_score)
        ratio = separation / max(best_score, 1.0)
        confidence = int(min(98.0, 62.0 + min(best_score, 40.0) * 0.55 + ratio * 25.0))

    full_text = " ".join(text for text, _weight in sections)
    tags: list[str] = []
    for label, markers in _GEO_RULES:
        if any(_contains(full_text, marker) for marker in markers):
            tags.append(label)
    for label, markers in _TAG_RULES:
        if any(_contains(full_text, marker) for marker in markers):
            tags.append(label)
    # Keep tags compact and deterministic. Topic itself is not repeated as a tag.
    unique: list[str] = []
    for tag in tags:
        if tag == topic or tag in unique:
            continue
        unique.append(tag)
        if len(unique) >= 4:
            break

    return TopicDecision(
        topic=topic,
        tags=tuple(unique),
        confidence=confidence,
        fingerprint=fingerprint_context(context),
        manual=False,
    )


class TopicAssignmentStore:
    VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self.rows: dict[str, dict[str, object]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict) or int(payload.get("version") or 0) != self.VERSION:
            return
        source = payload.get("groups")
        if not isinstance(source, dict):
            return
        self.rows = {str(key): dict(value) for key, value in source.items() if isinstance(value, dict)}

    def resolve(self, group_id: int, context: dict[str, object]) -> tuple[TopicDecision, bool]:
        key = str(int(group_id))
        fingerprint = fingerprint_context(context)
        current = self.rows.get(key)
        if current and bool(current.get("manual")):
            topic = str(current.get("topic") or "Інше")
            if topic not in TOPIC_CATEGORIES:
                topic = "Інше"
            tags = tuple(str(value) for value in current.get("tags", []) if str(value).strip())[:4]
            return TopicDecision(topic, tags, 100, fingerprint, True), False
        if current and str(current.get("fingerprint") or "") == fingerprint:
            topic = str(current.get("topic") or "Інше")
            if topic in TOPIC_CATEGORIES:
                tags = tuple(str(value) for value in current.get("tags", []) if str(value).strip())[:4]
                return TopicDecision(
                    topic=topic,
                    tags=tags,
                    confidence=int(current.get("confidence") or 0),
                    fingerprint=fingerprint,
                    manual=False,
                ), False

        decision = classify_topic_context(context)
        self.rows[key] = {
            **asdict(decision),
            "tags": list(decision.tags),
            "updated_at": datetime.now(KYIV).isoformat(timespec="seconds"),
        }
        return decision, True

    def set_manual(self, group_id: int, topic: str, tags: Iterable[str] = ()) -> None:
        value = str(topic or "").strip()
        if value not in TOPIC_CATEGORIES:
            raise ValueError("Невідома тема: " + value)
        self.rows[str(int(group_id))] = {
            "topic": value,
            "tags": [str(tag).strip() for tag in tags if str(tag).strip()][:4],
            "confidence": 100,
            "fingerprint": "",
            "manual": True,
            "updated_at": datetime.now(KYIV).isoformat(timespec="seconds"),
        }
        self.save()

    def clear_manual(self, group_id: int) -> None:
        self.rows.pop(str(int(group_id)), None)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        payload = {
            "version": self.VERSION,
            "updated_at": datetime.now(KYIV).isoformat(timespec="seconds"),
            "groups": self.rows,
        }
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
