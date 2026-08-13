from __future__ import annotations

import logging
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from .embedded_media import extract_embedded_media
from .media_candidates import MediaCandidate, deduplicate_media_candidates, extract_html_media
from .media_hint_store_v1_2_rc3 import SourceMediaHintStore
from .media_priority_v1_2 import prefer_real_video
from .models import Article
from .network import NetworkError, fetch_url

logger = logging.getLogger("content_agent.media")
_VIDEO_EXT = (".mp4", ".webm", ".mov", ".m4v")


class _RelatedPageParser(HTMLParser):
    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.canonical: list[str] = []
        self.player_pages: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).casefold(): str(value or "") for key, value in attrs}
        tag = tag.casefold()
        if tag == "link" and "canonical" in values.get("rel", "").casefold():
            href = urljoin(self.page_url, values.get("href", ""))
            if href.startswith(("http://", "https://")):
                self.canonical.append(href)
        if tag == "meta" and values.get("property", "").casefold() == "og:url":
            href = urljoin(self.page_url, values.get("content", ""))
            if href.startswith(("http://", "https://")):
                self.canonical.append(href)
        if tag == "a":
            href = urljoin(self.page_url, values.get("href", ""))
            classes = values.get("class", "").casefold()
            path = urlsplit(href).path.casefold()
            host = (urlsplit(href).hostname or "").casefold()
            if path.endswith(_VIDEO_EXT) or "video_player" in classes or host.endswith("telesco.pe"):
                if href.startswith(("http://", "https://")):
                    self.player_pages.append(href)


def _page_variants(url: str) -> list[str]:
    result = [url]
    try:
        parts = urlsplit(url)
    except ValueError:
        return result
    host = (parts.hostname or "").casefold()
    pieces = [piece for piece in parts.path.split("/") if piece]
    if host in {"t.me", "telegram.me", "www.t.me"} and len(pieces) >= 2 and pieces[-1].isdigit():
        channel, post_id = pieces[-2], pieces[-1]
        result.append(f"https://t.me/{channel}/{post_id}?embed=1&mode=tme")
        result.append(f"https://t.me/s/{channel}/{post_id}")
    return list(dict.fromkeys(result))


def _discover_page(url: str, source_label: str, *, follow_related: bool = True) -> list[MediaCandidate]:
    try:
        response = fetch_url(
            url,
            headers={"Accept": "text/html,application/xhtml+xml"},
            max_bytes=8 * 1024 * 1024,
            allowed_content_types={"text/html", "application/xhtml+xml"},
            timeout=45,
            max_redirects=5,
        )
    except NetworkError as exc:
        logger.info("RC3 media page unavailable source=%s host=%s error=%s", source_label, (urlsplit(url).hostname or ""), exc)
        return []
    html = response.body.decode("utf-8", errors="replace")
    final_url = response.final_url
    candidates = [
        *extract_html_media(html, final_url, source_label),
        *extract_embedded_media(html, final_url, source_label),
    ]
    if not follow_related:
        return prefer_real_video(deduplicate_media_candidates(candidates))

    parser = _RelatedPageParser(final_url)
    parser.feed(html)
    related: list[str] = []
    current_key = urlunsplit((*urlsplit(final_url)[:4], ""))
    for item in [*parser.canonical, *parser.player_pages]:
        try:
            key = urlunsplit((*urlsplit(item)[:4], ""))
        except ValueError:
            continue
        if key != current_key and item not in related:
            related.append(item)
    for item in related[:4]:
        candidates.extend(_discover_page(item, source_label, follow_related=False))
    return prefer_real_video(deduplicate_media_candidates(candidates))


def discover_group_media_rc3(articles: list[Article]) -> list[MediaCandidate]:
    """Prefer collection-time hints, then live source/canonical/player discovery."""

    store = SourceMediaHintStore()
    candidates: list[MediaCandidate] = []
    for article in articles:
        if not article.url:
            continue
        label = article.source_name or article.title or article.url
        stored = store.get(article.url)
        for item in stored:
            if item.origin == "telegram:player-page":
                candidates.extend(_discover_page(item.url, label, follow_related=False))
            else:
                candidates.append(item)
        for variant in _page_variants(article.url):
            candidates.extend(_discover_page(variant, label, follow_related=True))
    result = prefer_real_video(deduplicate_media_candidates(candidates))
    logger.info(
        "RC3 media discovery sources=%s candidates=%s videos=%s",
        len(articles),
        len(result),
        sum(item.kind == "video" for item in result),
    )
    return result
