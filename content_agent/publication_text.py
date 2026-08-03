from __future__ import annotations

from dataclasses import dataclass

from .editorial_memory import split_threads_chain

# The editor owns one canonical news text. All platform adaptation is purely
# technical and must never silently rewrite or discard facts.
EDITORIAL_TEXT_LIMIT = 900
TELEGRAM_MEDIA_CAPTION_LIMIT = 1024

FUND_FOOTER = (
    "Підтримайте збір Благодійного фонду UA FREE на потреби ЗСУ. "
    "Донат і всі реквізити: https://uafree.org/donate/"
)
THREADS_FUND_FOOTER = "Підтримайте збір UA FREE на потреби ЗСУ: https://uafree.org/donate/"
PLATFORM_LIMITS = {
    "facebook": 63_000,
    "threads": 500,  # physical limit of every item in the automatic chain
    "linkedin": 3_000,
    "telegram": 12_000,
}


class TextLimitError(ValueError):
    pass


@dataclass(slots=True)
class TextMetrics:
    platform: str
    length: int
    limit: int
    parts: int = 1
    valid: bool = True


def source_suffix(url: str) -> str:
    return f"Джерело: {url.strip()}" if url.strip() else ""


def footer_for(platform: str) -> str:
    return THREADS_FUND_FOOTER if platform == "threads" else FUND_FOOTER


def compose_publication_text(core_text: str, platform: str, *, include_source_link: bool, source_url: str) -> str:
    pieces = [core_text.strip(), footer_for(platform)]
    if include_source_link and source_url.strip():
        pieces.append(source_suffix(source_url))
    return "\n\n".join(piece for piece in pieces if piece)


def core_limit(platform: str, *, include_source_link: bool, source_url: str) -> int:
    """Compatibility helper for old data and tests.

    FIX28 has one canonical 900-character editor. Threads no longer truncates the
    text to one post: it publishes an automatic reply chain. Telegram with media
    is checked against its real caption limit after footer/source composition.
    """

    del include_source_link, source_url
    if platform in {"facebook", "threads", "linkedin", "telegram"}:
        return EDITORIAL_TEXT_LIMIT
    return EDITORIAL_TEXT_LIMIT


def telegram_split(text: str, limit: int = 4096) -> list[str]:
    remaining = text.strip()
    chunks: list[str] = []
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n\n", 0, limit + 1)
        if cut < limit // 3:
            cut = remaining.rfind("\n", 0, limit + 1)
        if cut < limit // 3:
            cut = remaining.rfind(" ", 0, limit + 1)
        if cut < limit // 3:
            cut = limit
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    return chunks or [""]


def validate_editorial_text(text: str) -> None:
    value = str(text or "").strip()
    if not value:
        raise TextLimitError("Текст публікації порожній.")
    if len(value) > EDITORIAL_TEXT_LIMIT:
        raise TextLimitError(
            f"Текст публікації має {len(value)} символів при ліміті {EDITORIAL_TEXT_LIMIT}. "
            "Залиште максимум фактів і приберіть повтори або вступну воду."
        )


def metrics_for(text: str, platform: str) -> TextMetrics:
    limit = PLATFORM_LIMITS[platform]
    if platform == "threads":
        parts = split_threads_chain(text, limit)
        return TextMetrics(
            platform,
            len(text),
            limit,
            parts=len(parts),
            valid=all(len(part) <= limit for part in parts),
        )
    if platform == "telegram":
        parts = len(telegram_split(text))
        return TextMetrics(platform, len(text), limit, parts=parts, valid=len(text) <= limit)
    return TextMetrics(platform, len(text), limit, valid=len(text) <= limit)


def validate_text(text: str, platform: str) -> None:
    metrics = metrics_for(text, platform)
    if not metrics.valid:
        raise TextLimitError(
            f"Текст для {platform} має {metrics.length} символів при ліміті {metrics.limit}. "
            "Скоротіть його перед постановкою в чергу."
        )


def validate_media_message(text: str, platform: str, *, has_media: bool) -> None:
    """Validate one composed platform message without changing its content."""

    validate_text(text, platform)
    if platform == "telegram" and has_media and len(text) > TELEGRAM_MEDIA_CAPTION_LIMIT:
        raise TextLimitError(
            f"Готовий підпис Telegram має {len(text)} символів при ліміті "
            f"{TELEGRAM_MEDIA_CAPTION_LIMIT}. Скоротіть текст або вимкніть посилання на джерело."
        )
