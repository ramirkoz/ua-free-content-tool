from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .article_extractor import extract_article
from .models import CollectedArticle, Source
from .news_logic import is_today_kyiv
from .network import NetworkError, fetch_url


class CollectorError(RuntimeError):
    pass


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"br", "p", "div", "li", "blockquote"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return "\n".join(line.strip() for line in "".join(self.parts).splitlines() if line.strip())


def _strip_html(value: str) -> str:
    parser = _TextParser()
    parser.feed(value or "")
    return parser.text()


def _first_text(element: ET.Element, names: list[str]) -> str:
    for child in element.iter():
        local = child.tag.rsplit("}", 1)[-1].lower()
        if local in names and child.text:
            return child.text.strip()
    return ""


def parse_rss(xml_bytes: bytes) -> list[CollectedArticle]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise CollectorError("RSS/Atom XML is invalid.") from exc
    items: list[CollectedArticle] = []
    candidates = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}]
    for node in candidates[:50]:
        title = _first_text(node, ["title"])
        link = _first_text(node, ["link"])
        if not link:
            for child in node:
                if child.tag.rsplit("}", 1)[-1].lower() == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        guid = _first_text(node, ["guid", "id"]) or link or title
        description = _first_text(node, ["encoded", "content", "description", "summary"])
        published = _first_text(node, ["pubdate", "published", "updated"]) or None
        text = _strip_html(description)
        if not guid or not (title or text):
            continue
        items.append(
            CollectedArticle(
                external_id=guid[:1000],
                title=title or text[:120] or "Без заголовка",
                url=link,
                raw_text=text,
                published_at=published,
            )
        )
    return items


class _TelegramPreviewParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.message_depth: int | None = None
        self.text_depth: int | None = None
        self.current_post = ""
        self.current_time: str | None = None
        self.current_text: list[str] = []
        self.items: list[CollectedArticle] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        attrs_dict = {key: value or "" for key, value in attrs}
        classes = set(attrs_dict.get("class", "").split())
        if tag.lower() == "div" and "tgme_widget_message" in classes and attrs_dict.get("data-post"):
            self.message_depth = self.depth
            self.current_post = attrs_dict["data-post"]
            self.current_time = None
            self.current_text = []
        elif self.message_depth is not None and tag.lower() == "div" and "tgme_widget_message_text" in classes:
            self.text_depth = self.depth
        elif self.message_depth is not None and tag.lower() == "time" and attrs_dict.get("datetime"):
            self.current_time = attrs_dict["datetime"]
        elif self.text_depth is not None and tag.lower() in {"br", "p", "div", "li", "blockquote"}:
            self.current_text.append("\n")

    def handle_data(self, data: str) -> None:
        if self.text_depth is not None:
            self.current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.text_depth == self.depth:
            self.text_depth = None
        if self.message_depth == self.depth:
            text = "\n".join(
                line.strip()
                for line in "".join(self.current_text).splitlines()
                if line.strip()
            )
            if self.current_post and text:
                self.items.append(
                    CollectedArticle(
                        external_id=self.current_post,
                        title=text.splitlines()[0][:160],
                        url=f"https://t.me/{self.current_post}",
                        raw_text=text,
                        published_at=self.current_time,
                    )
                )
            self.message_depth = None
            self.current_post = ""
            self.current_time = None
            self.current_text = []
        self.depth = max(0, self.depth - 1)

def normalize_telegram_preview_url(value: str) -> str:
    value = value.strip()
    if value.startswith("@"):
        username = value[1:]
    else:
        parts = urlsplit(value if "://" in value else "https://" + value)
        if parts.hostname not in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
            raise CollectorError("Telegram source must use t.me or @channel.")
        path = parts.path.strip("/")
        username = path[2:] if path.startswith("s/") else path.split("/", 1)[0]
    if not re.fullmatch(r"[A-Za-z0-9_]{5,}", username):
        raise CollectorError("Telegram public channel username is invalid.")
    return f"https://t.me/s/{username}"


def parse_telegram_preview(html: str) -> list[CollectedArticle]:
    parser = _TelegramPreviewParser()
    parser.feed(html)
    return parser.items[-30:]


def _fetch_article_text(url: str, fallback: str) -> str:
    if not url or len(fallback) >= 700:
        return fallback
    try:
        response = fetch_url(
            url,
            max_bytes=3 * 1024 * 1024,
            allowed_content_types={"text/html", "application/xhtml+xml"},
            timeout=20,
        )
        _, text = extract_article(response.body.decode("utf-8", errors="replace"))
        return text if len(text) > len(fallback) else fallback
    except NetworkError:
        return fallback


def collect_source(source: Source) -> list[CollectedArticle]:
    try:
        if source.kind == "rss":
            response = fetch_url(
                source.url,
                max_bytes=5 * 1024 * 1024,
                allowed_content_types={
                    "application/rss+xml",
                    "application/atom+xml",
                    "application/xml",
                    "text/xml",
                    "text/plain",
                },
                timeout=30,
            )
            items = parse_rss(response.body)
            for item in items[:15]:
                item.raw_text = _fetch_article_text(item.url, item.raw_text)
            return [item for item in items[:30] if is_today_kyiv(item.published_at)]
        if source.kind == "telegram":
            url = normalize_telegram_preview_url(source.url)
            response = fetch_url(
                url,
                max_bytes=5 * 1024 * 1024,
                allowed_content_types={"text/html"},
                timeout=30,
            )
            return [
                item for item in parse_telegram_preview(response.body.decode("utf-8", errors="replace"))
                if is_today_kyiv(item.published_at)
            ]
        if source.kind == "url":
            response = fetch_url(
                source.url,
                max_bytes=5 * 1024 * 1024,
                allowed_content_types={"text/html", "application/xhtml+xml"},
                timeout=30,
            )
            title, text = extract_article(response.body.decode("utf-8", errors="replace"))
            external = hashlib.sha256(source.url.encode("utf-8")).hexdigest()
            # A plain URL has no trustworthy publication date. The application only
            # accepts today's news, so undated pages are deliberately skipped.
            return []
    except NetworkError as exc:
        raise CollectorError(str(exc)) from exc
    raise CollectorError(f"Unsupported source kind: {source.kind}")
