from __future__ import annotations

import re


_TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Київ", ("київ", "києв", "киев", "kyiv", "kiev")),
    (
        "Війна",
        (
            "війна", "військ", "зсу", "фронт", "обстріл", "ракет", "дрон", "шахед",
            "окуп", "бойов", "war ", "military", "missile", "drone", "russian army",
            "российск", "войн", "фронт", "обстрел", "бпла",
        ),
    ),
    (
        "Політика",
        (
            "президент", "верховн", "рада", "кабмін", "уряд", "міністр", "вибор",
            "парті", "депутат", "зеленськ", "політик", "парламент", "president", "election",
            "government", "minister", "politic", "парламент", "выбор", "депутат", "министр",
        ),
    ),
    (
        "Міжнародка",
        (
            "сша", "єс", "євросоюз", "нато", "оон", "g7", "g20", "трамп", "макрон",
            "мерц", "стармер", "польщ", "німеч", "франц", "британ", "китай", "інді",
            "япон", "iran", "israel", "usa", "united states", "european union", "nato",
            "china", "germany", "france", "britain", "международ", "евросоюз", "нато",
        ),
    ),
    (
        "Економіка",
        (
            "економ", "бюджет", "інфляц", "гривн", "курс валют", "нбу", "подат", "мит",
            "експорт", "імпорт", "ввп", "ринок", "econom", "inflation", "gdp", "tariff",
            "налог", "бюджет", "эконом", "рубл", "долар", "доллар",
        ),
    ),
    (
        "Технології",
        (
            "штучн", "ai ", "ai-", "openai", "chatgpt", "google", "apple", "microsoft",
            "meta ", "кібер", "хакер", "чип", "процесор", "gpu", "software", "tech",
            "robot", "робот", "стартап", "кібербезп", "технолог", "ии ", "нейромереж",
        ),
    ),
    (
        "Наука",
        (
            "науков", "дослідж", "вчен", "космос", "nasa", "esa", "астроном", "медицин",
            "здоров", "біолог", "фізик", "science", "research", "scientist", "space", "study",
            "исследован", "учен", "космос",
        ),
    ),
    (
        "Бізнес",
        (
            "компан", "бізнес", "угод", "інвест", "акці", "прибут", "стартап", "amazon",
            "tesla", "business", "company", "deal", "investment", "funding", "revenue",
            "компан", "бизнес", "инвест", "сделк",
        ),
    ),
    (
        "Культура",
        (
            "фільм", "серіал", "музик", "книг", "театр", "мистец", "актор", "режисер",
            "film", "movie", "music", "series", "culture", "фильм", "сериал", "музык",
        ),
    ),
    (
        "Спорт",
        (
            "футбол", "баскет", "теніс", "олімпі", "матч", "чемпіон", "спорт", "boxing",
            "football", "tennis", "sport", "матч", "чемпион",
        ),
    ),
    (
        "Суспільство",
        (
            "освіт", "школ", "універс", "суд", "поліц", "корупц", "злочин", "соціаль",
            "демограф", "суспіль", "education", "court", "police", "society", "crime",
            "образован", "суд", "полици", "общество",
        ),
    ),
)

_UKRAINE_MARKERS = (
    "україн", "украин", "ukrain", "львів", "харків", "одес", "дніпр", "запоріж",
    "миколаїв", "херсон", "полтав", "черніг", "черкас", "сум", "рівн", "терноп",
    "івано-франків", "ужгород", "луцьк", "кропивниць",
)


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def central_topic(title: str) -> str:
    """Return exactly one compact editorial topic for an Inbox row.

    The classifier is deliberately deterministic and local. RC8 uses the
    canonical headline only, so adding this column does not trigger AI calls,
    network traffic or a database migration during Inbox refreshes.
    """

    text = f" {_normalized(title)} "
    if not text.strip():
        return "Інше"
    for label, markers in _TOPIC_RULES:
        if any(marker in text for marker in markers):
            return label
    if any(marker in text for marker in _UKRAINE_MARKERS):
        return "Україна"
    return "Інше"
