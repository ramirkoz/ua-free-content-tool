from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Article, NewsGroup

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_NUMBER_RE = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?(?:\s?%|\s?(?:млн|млрд|тис\.?|km|км|m|м|kg|кг|gb|гб|mb|мб|mw|мвт|gw|гвт|usd|eur|грн|₴|\$|€))?", re.IGNORECASE)
_LATIN_ENTITY_RE = re.compile(r"\b(?:[A-Z][A-Za-z0-9._+\-/]{2,}|[A-Z0-9]{2,}(?:[-_/][A-Z0-9]{1,})*)\b")
_CYRILLIC_NAME_RE = re.compile(r"(?u)\b[А-ЯІЇЄҐ][а-яіїєґ'’\-]{2,}\b")
_UNCERTAINTY_RE = re.compile(
    r"(?iu)\b(?:може|можуть|планує|планують|очікує|очікують|ймовірно|можливо|"
    r"заявив|заявила|заявили|повідомив|повідомила|повідомили|за даними|за словами|"
    r"could|may|might|plans?|planned|expected|reportedly|according to|said|says|"
    r"может|могут|планирует|планируют|ожидается|вероятно|возможно|сообщил|заявил|по данным)\b"
)
_HIGH_RISK_RE = re.compile(
    r"(?iu)\b(?:перш(?:ий|а|е|і)\s+(?:у\s+світі|в\s+світі|в\s+історії)|"
    r"найбільш(?:ий|а|е|і)|найшвидш(?:ий|а|е|і)|найпотужніш(?:ий|а|е|і)|рекордн(?:ий|а|е|і)|"
    r"first[- ]ever|world['’]?s first|largest|biggest|fastest|most powerful|record[- ]breaking|"
    r"перв(?:ый|ая|ое|ые)\s+в\s+мире|крупнейш(?:ий|ая|ее|ие)|сам(?:ый|ая|ое)\s+быстр|рекордн)\b"
)
_PROMO_LINE = re.compile(
    r"(?iu)^(?:підписатися|подписаться|subscribe|реклама|advertis|наш\s+бот|бот\s*:|"
    r"надіслати\s+контент|прислать\s+контент|джерело\s*:|источник\s*:|source\s*:).*$"
)
_SEPARATOR = "\n\n---\n\n"
_TEXT_LABEL = "\nТЕКСТ:\n"


@dataclass(frozen=True, slots=True)
class EvidencePack:
    text: str
    source_count: int
    selected_sentences: int
    total_sentences: int
    truncated: bool


def _clean_text(value: str) -> str:
    rows: list[str] = []
    for raw in str(value or "").splitlines():
        line = " ".join(raw.split()).strip()
        if not line or _PROMO_LINE.match(line):
            continue
        rows.append(line)
    return "\n".join(rows)


def _sentences(value: str) -> list[str]:
    text = _clean_text(value)
    if not text:
        return []
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]
    if len(parts) == 1 and "\n" in text:
        parts = [part.strip() for part in text.splitlines() if part.strip()]
    return parts or [text]


def _score_sentence(index: int, sentence: str) -> float:
    score = max(0.0, 12.0 - index * 0.35)
    score += min(24.0, 8.0 * len(_NUMBER_RE.findall(sentence)))
    score += min(18.0, 6.0 * len(_LATIN_ENTITY_RE.findall(sentence)))
    score += min(12.0, 3.0 * len(_CYRILLIC_NAME_RE.findall(sentence)))
    if "«" in sentence or '"' in sentence:
        score += 7.0
    if _UNCERTAINTY_RE.search(sentence):
        score += 8.0
    if _HIGH_RISK_RE.search(sentence):
        score += 12.0
    if re.search(r"(?iu)\b(?:через|внаслідок|тому що|щоб|після|досяг|зрос|зниз|because|after|due to|reached|rose|fell|из-за|после|достиг)\b", sentence):
        score += 4.0
    return score


def _clip_at_word(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    cut = text.rfind(" ", 0, limit - 1)
    if cut < max(8, limit // 2):
        cut = limit - 1
    return text[:cut].rstrip(" ,;:-") + "…"


def _select_article_sentences(article: Article, budget: int) -> tuple[str, int, int, bool]:
    sentences = _sentences(article.raw_text)
    total = len(sentences)
    if not sentences or budget <= 0:
        return "", 0, total, bool(sentences)

    selected: set[int] = set()
    used = 0

    # Keep the lead only when it fits. A pathological long lead must not crowd out
    # later dates, numbers, entities or attribution.
    if len(sentences[0]) <= budget:
        selected.add(0)
        used = len(sentences[0])

    ranked = sorted(range(len(sentences)), key=lambda idx: (-_score_sentence(idx, sentences[idx]), idx))
    for index in ranked:
        if index in selected:
            continue
        sentence = sentences[index]
        addition = len(sentence) + (1 if selected else 0)
        if used + addition <= budget:
            selected.add(index)
            used += addition

    if not selected:
        best_index = ranked[0]
        fragment = _clip_at_word(sentences[best_index], budget)
        return fragment, 1 if fragment else 0, total, True

    body = " ".join(sentence for index, sentence in enumerate(sentences) if index in selected).strip()
    return body, len(selected), total, len(selected) < total


def _source_header(
    index: int,
    total: int,
    article: Article,
    *,
    include_urls: bool,
    budget: int,
) -> tuple[str, bool]:
    """Create a compact metadata header that never consumes another source's share."""

    budget = max(1, int(budget))
    name = " ".join(str(article.source_name or "невідоме джерело").split())
    title = " ".join(str(article.title or "без заголовка").split())
    published = str(article.published_at or "не визначено").strip()
    rows = [
        f"ДЖЕРЕЛО {index}/{total}",
        f"НАЗВА: {name}",
        f"ЗАГОЛОВОК: {title}",
        f"ЧАС: {published}",
    ]
    if include_urls and article.url:
        rows.append(f"URL: {article.url}")

    selected: list[str] = []
    used = 0
    clipped = False
    for row in rows:
        addition = len(row) + (1 if selected else 0)
        if used + addition <= budget:
            selected.append(row)
            used += addition
            continue
        remaining = budget - used - (1 if selected else 0)
        if remaining > 8:
            selected.append(_clip_at_word(row, remaining))
        clipped = True
        break

    if not selected:
        return _clip_at_word(rows[0], budget), True
    return "\n".join(selected), clipped or len(selected) < len(rows)


def build_evidence_pack(
    group: NewsGroup,
    *,
    max_chars: int = 7600,
    include_urls: bool = False,
) -> EvidencePack:
    """Build a deterministic bounded factual dossier for one merged news group.

    The total character budget is divided between sources before sentence
    selection. This prevents a long first article or verbose metadata from
    deleting later sources from the pack. Editorial memory is never included.
    """

    articles = list(group.articles)
    total_sources = len(articles)
    if not articles:
        return EvidencePack("", 0, 0, 0, False)

    max_chars = max(900, int(max_chars))
    separator = _SEPARATOR
    separator_total = len(separator) * max(0, total_sources - 1)
    if separator_total >= max_chars:
        separator = "\n"
        separator_total = max(0, total_sources - 1)

    available = max(1, max_chars - separator_total)
    base_share, remainder = divmod(available, total_sources)

    selected_total = 0
    sentence_total = 0
    truncated = False
    blocks: list[str] = []

    for offset, article in enumerate(articles):
        index = offset + 1
        block_budget = base_share + (1 if offset < remainder else 0)
        if block_budget <= 0:
            truncated = True
            continue

        # In normal groups this keeps a rich title/name/date header. In a very
        # large merged group it contracts metadata first, preserving room for a
        # factual sentence from every source.
        header_budget = min(240, max(24, block_budget // 3))
        header_budget = min(header_budget, block_budget)
        header, header_clipped = _source_header(
            index,
            total_sources,
            article,
            include_urls=include_urls,
            budget=header_budget,
        )
        truncated = truncated or header_clipped

        remaining = max(0, block_budget - len(header))
        label = _TEXT_LABEL if remaining > len(_TEXT_LABEL) + 8 else ("\n" if remaining > 1 else "")
        body_budget = max(0, remaining - len(label))
        body, selected, count, body_truncated = _select_article_sentences(article, body_budget)
        selected_total += selected
        sentence_total += count
        truncated = truncated or body_truncated

        block = f"{header}{label}{body}" if body or label else header
        if len(block) > block_budget:
            block = _clip_at_word(block, block_budget)
            truncated = True
        blocks.append(block)

    text = separator.join(blocks).strip()
    if len(text) > max_chars:
        # Defensive bound only. The per-source allocation above should make this
        # unreachable for ordinary inputs.
        text = _clip_at_word(text, max_chars)
        truncated = True

    return EvidencePack(
        text=text,
        source_count=total_sources,
        selected_sentences=selected_total,
        total_sentences=sentence_total,
        truncated=truncated,
    )
