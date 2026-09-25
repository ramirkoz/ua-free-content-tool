from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from .media_candidates import MediaCandidate, deduplicate_media_candidates
from .media_priority_v1_2 import prefer_real_video
from .network import NetworkError, fetch_url

logger = logging.getLogger("content_agent.media.telegram")

_STYLE_URL_RE = re.compile(r"(?i)(?:background(?:-image)?|poster)\s*:\s*url\(\s*(['\"]?)(.*?)\1\s*\)")
_MEDIA_CLASS_MARKERS = (
    "tgme_widget_message_photo",
    "tgme_widget_message_video",
    "tgme_widget_message_document",
    "tgme_widget_message_voice",
    "tgme_widget_message_grouped",
)
_VIDEO_ATTRS = ("src", "data-video", "data-video-url", "data-mp4", "data-webm", "data-file")
_NOISE_WORDS = (
    "/img/emoji/",
    "emoji",
    "reaction",
    "userpic",
    "avatar",
    "favicon",
    "sprite",
    "logo",
    "icon",
    "badge",
    "sticker",
)
_VIDEO_EXT = (".mp4", ".webm", ".mov", ".m4v")
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def telegram_post_parts(url: str) -> tuple[str, str] | None:
    try:
        parts = urlsplit(str(url or "").strip())
    except ValueError:
        return None
    host = (parts.hostname or "").casefold()
    if host not in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
        return None
    pieces = [piece for piece in parts.path.split("/") if piece]
    if len(pieces) < 2 or not pieces[-1].isdigit():
        return None
    return pieces[-2], pieces[-1]


def telegram_embed_url(url: str) -> str:
    parts = telegram_post_parts(url)
    if parts is None:
        return ""
    channel, post_id = parts
    return f"https://t.me/{channel}/{post_id}?embed=1&mode=tme"


def _safe_media_url(base_url: str, value: str) -> str:
    raw = str(value or "").strip()
    if not raw or raw.startswith(("data:", "blob:", "javascript:")):
        return ""
    try:
        absolute = urljoin(base_url, raw)
        parts = urlsplit(absolute)
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        return ""
    clean = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
    lowered = clean.casefold()
    if any(word in lowered for word in _NOISE_WORDS):
        return ""
    host = (parts.hostname or "").casefold()
    # Telegram post media is served through telesco.pe/Telegram CDN. Reject page
    # chrome and arbitrary linked images even if they happen to sit in the embed.
    if not (
        host.endswith("telesco.pe")
        or "telegram" in host
        or host.endswith("cdninstagram.com")
    ):
        return ""
    return clean


def _kind(url: str, fallback: str) -> str:
    path = urlsplit(url).path.casefold()
    if path.endswith(_VIDEO_EXT):
        return "video"
    if path.endswith(_IMAGE_EXT):
        return "image"
    return fallback


class _TelegramPostMediaParser(HTMLParser):
    def __init__(self, page_url: str, source_label: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.source_label = source_label
        self.stack: list[tuple[str, bool]] = []
        self.items: list[MediaCandidate] = []

    def _inside_media(self) -> bool:
        return bool(self.stack and self.stack[-1][1])

    def _append(self, value: str, *, fallback: str, origin: str, score: int) -> None:
        url = _safe_media_url(self.page_url, value)
        if not url:
            return
        self.items.append(
            MediaCandidate(
                url=url,
                kind=_kind(url, fallback),
                source_label=self.source_label,
                origin=origin,
                score=score,
            )
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).casefold(): str(value or "") for key, value in attrs}
        classes = values.get("class", "").casefold()
        parent_media = self._inside_media()
        current_media = parent_media or any(marker in classes for marker in _MEDIA_CLASS_MARKERS)
        self.stack.append((tag.casefold(), current_media))

        if not current_media:
            return
        lowered_tag = tag.casefold()
        if lowered_tag in {"video", "source"}:
            for attribute in _VIDEO_ATTRS:
                if values.get(attribute):
                    self._append(
                        values[attribute],
                        fallback="video",
                        origin=f"telegram:{lowered_tag}:{attribute}",
                        score=150,
                    )
        if lowered_tag == "a":
            href = values.get("href", "")
            if urlsplit(href).path.casefold().endswith(_VIDEO_EXT):
                self._append(href, fallback="video", origin="telegram:a:video", score=145)
        style = values.get("style", "")
        for match in _STYLE_URL_RE.finditer(style):
            # A Telegram photo is normally the background of the exact message's
            # photo wrapper. Video posters stay below a real video candidate.
            score = 125 if "photo" in classes else 85
            self._append(
                match.group(2),
                fallback="image",
                origin="telegram:message-background",
                score=score,
            )

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        wanted = tag.casefold()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == wanted:
                del self.stack[index:]
                break


def extract_telegram_post_media(html: str, page_url: str, source_label: str = "") -> list[MediaCandidate]:
    parser = _TelegramPostMediaParser(page_url, source_label)
    parser.feed(str(html or ""))
    return prefer_real_video(deduplicate_media_candidates(parser.items))


def discover_telegram_post_media(url: str, source_label: str = "") -> list[MediaCandidate]:
    embed = telegram_embed_url(url)
    if not embed:
        return []
    try:
        response = fetch_url(
            embed,
            headers={"Accept": "text/html,application/xhtml+xml"},
            max_bytes=5 * 1024 * 1024,
            allowed_content_types={"text/html", "application/xhtml+xml"},
            timeout=35,
            max_redirects=5,
        )
    except NetworkError as exc:
        logger.info("Telegram exact-post media unavailable url=%s error=%s", embed, exc)
        return []
    html = response.body.decode("utf-8", errors="replace")
    result = extract_telegram_post_media(html, response.final_url, source_label)
    logger.info(
        "Telegram exact-post media source=%s candidates=%s videos=%s",
        source_label,
        len(result),
        sum(item.kind == "video" for item in result),
    )
    return result
