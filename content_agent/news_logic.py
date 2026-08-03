from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from typing import Iterable

from .models import Article, NewsGroup
from .scheduling import KYIV

_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яІіЇїЄєҐґ']+", re.UNICODE)
_STOPWORDS = {
    "і", "й", "та", "але", "або", "що", "це", "як", "у", "в", "на", "до", "з", "із", "зі", "за", "для", "про",
    "від", "по", "під", "над", "при", "не", "так", "же", "ще", "вже", "було", "буде", "є", "був", "була", "були",
    "який", "яка", "яке", "які", "через", "після", "перед", "між", "серед", "свої", "свій", "свою", "їх", "його", "її",
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "from", "is", "are", "was", "were",
    "и", "а", "но", "что", "это", "как", "в", "на", "до", "с", "за", "для", "от", "по", "не", "уже", "еще",
}
_HIGH_IMPACT = {
    "вибух", "вибухи", "удар", "обстріл", "атака", "дрон", "дрони", "ракета", "ракети", "загибл", "поранен",
    "евакуац", "наступ", "фронт", "зсу", "пожеж", "катастроф", "аварі", "санкц", "перемир", "полон",
    "корупц", "затриман", "звільнен", "призначен", "закон", "постанова", "рішення", "мільярд", "мільйон",
}
_LINKEDIN = {
    "бізнес", "економік", "інвест", "грант", "фінанс", "партнерств", "муніцип", "управлін", "проєкт", "проект",
    "технолог", "ринок", "компан", "підприєм", "відновлен", "міжнарод", "розвиток", "робоч", "ваканс",
}
_HUMAN = {"дитин", "родин", "волонтер", "переселен", "ветеран", "лікар", "школ", "громад", "допомог", "врятув"}

# Compact synonym normalization for common Ukrainian news language. This is not
# an attempt to ship a linguistic research institute inside the executable. It
# just joins obvious paraphrases before the similarity calculation.
_CANONICAL_PREFIXES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("кабмін", "кабинет", "уряд"), "уряд"),
    (("ухвал", "прийн", "затверд", "підпис"), "рішення"),
    (("атак", "удар", "обстріл", "обстрел"), "атака"),
    (("дрон", "бпла", "шахед"), "дрон"),
    (("вибух", "взрыв"), "вибух"),
    (("виплат", "допомог", "пособ"), "виплата"),
    (("впо", "переселен"), "впо"),
    (("загин", "загиб", "жертв"), "загиблі"),
    (("поран", "постраждал"), "поранені"),
    (("звільн", "увільн"), "звільнення"),
    (("признач" ,), "призначення"),
    (("запоріж", "запорож"), "запоріжжя"),
    (("київ", "киев"), "київ"),
)

_ACTION_CANONICAL = {
    "рішення", "атака", "вибух", "виплата", "загиблі", "поранені",
    "звільнення", "призначення",
}


def parse_published_at(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError, OverflowError):
        pass
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KYIV)
    return parsed


def is_today_kyiv(value: str | None, *, now: datetime | None = None) -> bool:
    parsed = parse_published_at(value)
    if parsed is None:
        return False
    current = (now or datetime.now(KYIV)).astimezone(KYIV)
    return parsed.astimezone(KYIV).date() == current.date()


def _canonical_token(token: str) -> str:
    for prefixes, canonical in _CANONICAL_PREFIXES:
        if any(token.startswith(prefix) for prefix in prefixes):
            return canonical
    return token


def normalized_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text.casefold()):
        token = raw.strip("'")
        if len(token) < 3 or token in _STOPWORDS:
            continue
        # A light stem-like normalization catches common Ukrainian/Russian endings
        # without adding a multi-megabyte NLP dependency.
        for suffix in ("ами", "ями", "ого", "ому", "ими", "ій", "ий", "а", "у", "і", "и", "е", "я"):
            if len(token) > 6 and token.endswith(suffix):
                token = token[: -len(suffix)]
                break
        tokens.append(_canonical_token(token))
    return tokens


def _token_set(text: str, limit: int = 80) -> set[str]:
    counts = Counter(normalized_tokens(text))
    return {token for token, _ in counts.most_common(limit)}


def event_similarity(title_a: str, text_a: str, title_b: str, text_b: str) -> float:
    title_tokens_a = _token_set(title_a, 30)
    title_tokens_b = _token_set(title_b, 30)
    body_tokens_a = _token_set(f"{title_a} {text_a[:4000]}", 100)
    body_tokens_b = _token_set(f"{title_b} {text_b[:4000]}", 100)

    title_union = title_tokens_a | title_tokens_b
    body_union = body_tokens_a | body_tokens_b
    title_jaccard = len(title_tokens_a & title_tokens_b) / max(1, len(title_union))
    body_jaccard = len(body_tokens_a & body_tokens_b) / max(1, len(body_union))
    sequence = SequenceMatcher(None, " ".join(sorted(title_tokens_a)), " ".join(sorted(title_tokens_b))).ratio()

    numbers_a = set(re.findall(r"\b\d{1,6}\b", f"{title_a} {text_a[:2000]}"))
    numbers_b = set(re.findall(r"\b\d{1,6}\b", f"{title_b} {text_b[:2000]}"))
    number_bonus = 0.08 if numbers_a and numbers_b and numbers_a & numbers_b else 0.0

    shared = body_tokens_a & body_tokens_b
    entity_bonus = min(0.16, 0.035 * sum(1 for token in shared if len(token) >= 6))
    shared_actions = shared & _ACTION_CANONICAL
    action_bonus = 0.14 if shared_actions else 0.0
    # A shared place/person plus a shared action is a strong event anchor even
    # when headline wording differs substantially.
    long_shared = {token for token in shared if len(token) >= 6 and token not in _ACTION_CANONICAL}
    anchor_bonus = 0.12 if shared_actions and long_shared else 0.0
    return min(
        1.0,
        0.38 * title_jaccard
        + 0.30 * body_jaccard
        + 0.18 * sequence
        + number_bonus
        + entity_bonus
        + action_bonus
        + anchor_bonus,
    )


def belongs_to_group(title: str, text: str, articles: Iterable[Article], threshold: float = 0.38) -> bool:
    best = 0.0
    for article in articles:
        best = max(best, event_similarity(title, text, article.title, article.raw_text))
        if best >= threshold:
            return True
    return False


_TREND_GENERIC = {
    "данным", "данные", "розвідки", "разведки", "стало", "відомо", "известно",
    "планує", "планирует", "готує", "готовит", "заявив", "заявила", "сообщил",
    "повідомив", "повідомила", "назвав", "назвала", "може", "может", "буде", "будет",
    "після", "после", "перед", "щодо", "около", "сразу", "виборів", "выборов",
}

_TREND_CANONICAL: tuple[tuple[tuple[str, ...], str], ...] = (
    (("мобілізац",), "мобілізація"),
    (("мобилизац",), "мобилизация"),
    (("путін",), "Путін"),
    (("путин",), "Путин"),
    (("зеленськ",), "Зеленський"),
    (("зеленск",), "Зеленский"),
    (("госдум",), "Госдума"),
    (("держдум",), "Держдума"),
    (("дрон", "бпла", "шахед"), "дрони"),
    (("ракет",), "ракети"),
    (("обстріл", "атак", "удар"), "атака"),
    (("обстрел",), "атака"),
    (("вибух",), "вибухи"),
    (("взрыв",), "взрывы"),
)


def _trend_surface_words(group: NewsGroup) -> list[tuple[str, int, bool]]:
    counts: Counter[str] = Counter()
    display: dict[str, str] = {}
    proper: dict[str, bool] = {}
    titles = [group.canonical_title, *(item.title for item in group.articles)]
    for title in titles:
        for raw in _TOKEN_RE.findall(title):
            clean = raw.strip("'")
            folded = clean.casefold()
            if len(folded) < 4 or folded in _STOPWORDS or folded in _TREND_GENERIC or folded.isdigit():
                continue
            counts[folded] += 1
            display.setdefault(folded, clean)
            proper[folded] = proper.get(folded, False) or (clean[:1].isupper() and clean[1:].islower())
    ranked = sorted(
        counts,
        key=lambda word: (counts[word] * 5 + (4 if proper.get(word) else 0) + min(3, len(word) // 5)),
        reverse=True,
    )
    return [(display[word], counts[word], proper.get(word, False)) for word in ranked]


def _trend_canonical_word(word: str) -> str:
    folded = word.casefold()
    for prefixes, canonical in _TREND_CANONICAL:
        if any(prefix in folded for prefix in prefixes):
            return canonical
    return word


def extract_trend_queries(group: NewsGroup) -> list[str]:
    """Build several short Threads queries instead of one over-specific phrase."""
    words = _trend_surface_words(group)
    if not words:
        fallback = [token for token in normalized_tokens(group.canonical_title) if token not in _TREND_GENERIC]
        return [" ".join(fallback[:2])] if fallback else []

    entity = next((word for word, _count, is_proper in words if is_proper), words[0][0])
    action = next(
        (
            _trend_canonical_word(word)
            for word, _count, _proper in words
            if _trend_canonical_word(word).casefold() != _trend_canonical_word(entity).casefold()
            and any(fragment in word.casefold() for fragment in _HIGH_IMPACT | {"мобілізац", "мобилизац"})
        ),
        "",
    )
    significant = [_trend_canonical_word(word) for word, _count, _proper in words[:6]]
    candidates: list[str] = []
    if action:
        candidates.append(f"{_trend_canonical_word(entity)} {action}")
    for word in [_trend_canonical_word(entity), action, *significant]:
        word = word.strip()
        if word and word.casefold() not in {item.casefold() for item in candidates}:
            candidates.append(word)
        if len(candidates) >= 4:
            break
    return candidates


def extract_trend_query(group: NewsGroup) -> str:
    queries = extract_trend_queries(group)
    return queries[0] if queries else ""


def _contains_fragment(tokens: Iterable[str], fragments: set[str]) -> bool:
    return any(any(fragment in token for fragment in fragments) for token in tokens)


def calculate_explosiveness(group: NewsGroup, threads_posts: int | None = None) -> tuple[int, int, dict[str, object], list[str]]:
    now = datetime.now(KYIV)
    published = [parse_published_at(item.published_at) for item in group.articles]
    published = [item.astimezone(KYIV) for item in published if item is not None]
    freshest_minutes = 24 * 60
    span_minutes = 24 * 60
    if published:
        freshest_minutes = max(0, int((now - max(published)).total_seconds() / 60))
        span_minutes = max(1, int((max(published) - min(published)).total_seconds() / 60))

    source_points = min(28, 9 + max(0, group.source_count - 1) * 6)
    freshness_points = max(0, 18 - int(freshest_minutes / 20))
    velocity = group.source_count / max(1.0, span_minutes / 60.0)
    velocity_points = min(18, round(7 * math.log2(1 + velocity)))

    tokens = normalized_tokens(" ".join([group.canonical_title, *(item.title for item in group.articles)]))
    impact_points = 15 if _contains_fragment(tokens, _HIGH_IMPACT) else 5
    media_points = 5 if group.media_drive_url else 0
    threads_points = 0 if threads_posts is None else min(16, int(4 * math.log2(1 + max(0, threads_posts))))

    score = max(0, min(100, source_points + freshness_points + velocity_points + impact_points + media_points + threads_points))
    confidence = min(96, 35 + min(35, group.source_count * 9) + (18 if threads_posts is not None else 0) + (8 if published else 0))

    professional = _contains_fragment(tokens, _LINKEDIN)
    human = _contains_fragment(tokens, _HUMAN)
    recommendations: list[str] = []
    if score >= 25:
        recommendations.append("telegram")
    if score >= 40 or human:
        recommendations.append("facebook")
    if score >= 55 or (threads_posts or 0) >= 5:
        recommendations.append("threads")
    if professional and score >= 30:
        recommendations.append("linkedin")
    if score >= 78 and "linkedin" not in recommendations and professional:
        recommendations.append("linkedin")

    details: dict[str, object] = {
        "sources": group.source_count,
        "freshest_minutes": freshest_minutes,
        "span_minutes": span_minutes,
        "mentions_per_hour": round(velocity, 2),
        "threads_posts": threads_posts,
        "partial": threads_posts is None,
        "query": extract_trend_query(group),
    }
    return score, confidence, details, recommendations
