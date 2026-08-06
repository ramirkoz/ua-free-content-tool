from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from .media_candidates import MediaCandidate, deduplicate_media_candidates

_STYLE_URL_RE = re.compile(
    r"(?i)(?:background(?:-image)?|poster)\s*:\s*url\(\s*(['\"]?)(.*?)\1\s*\)"
)
_VIDEO_ATTRIBUTE_NAMES = {
    "data-video",
    "data-video-url",
    "data-mp4",
    "data-webm",
    "data-file",
}
_IMAGE_ATTRIBUTE_NAMES = {
    "data-image",
    "data-photo",
    "data-thumbnail",
    "data-thumb",
    "data-poster",
}
_BLOCKED_WORDS = {"favicon", "sprite", "logo", "icon", "pixel", "tracking", "tracker"}


def _safe_http_url(base_url: str, value: str) -> str:
    raw = str(value or "").strip()
    if not raw or raw.startswith(("data:", "blob:", "javascript:")):
        return ""
    try:
        absolute = urljoin(base_url, raw)
        parts = urlsplit(absolute)
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return ""
    if parts.username or parts.password:
        return ""
    result = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
    lowered = result.casefold()
    if any(word in lowered for word in _BLOCKED_WORDS):
        return ""
    return result


def _kind_from_url(url: str, fallback: str) -> str:
    path = urlsplit(url).path.casefold()
    if path.endswith((".mp4", ".webm", ".mov", ".m4v")):
        return "video"
    if path.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return "image"
    return fallback


def _srcset_urls(value: str) -> list[str]:
    result: list[tuple[int, str]] = []
    for part in str(value or "").split(","):
        tokens = part.strip().split()
        if not tokens:
            continue
        weight = 0
        if len(tokens) > 1:
            descriptor = tokens[-1].casefold()
            try:
                if descriptor.endswith("w"):
                    weight = int(float(descriptor[:-1]))
                elif descriptor.endswith("x"):
                    weight = int(float(descriptor[:-1]) * 1000)
            except ValueError:
                weight = 0
        result.append((weight, tokens[0]))
    result.sort(key=lambda item: item[0], reverse=True)
    return [url for _weight, url in result]


class _EmbeddedMediaParser(HTMLParser):
    def __init__(self, page_url: str, source_label: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.source_label = source_label
        self.items: list[MediaCandidate] = []

    def _append(self, value: str, *, kind: str, origin: str, score: int) -> None:
        url = _safe_http_url(self.page_url, value)
        if not url:
            return
        self.items.append(
            MediaCandidate(
                url=url,
                kind=_kind_from_url(url, kind),
                source_label=self.source_label,
                origin=origin,
                score=score,
            )
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).casefold(): str(value or "") for key, value in attrs}
        style = values.get("style", "")
        for match in _STYLE_URL_RE.finditer(style):
            self._append(
                match.group(2),
                kind="image",
                origin="html:background-image",
                score=78,
            )

        for attribute in ("srcset", "data-srcset"):
            urls = _srcset_urls(values.get(attribute, ""))
            if urls:
                self._append(
                    urls[0],
                    kind="image",
                    origin=f"html:{attribute}",
                    score=72,
                )

        for attribute in _VIDEO_ATTRIBUTE_NAMES:
            if values.get(attribute):
                self._append(
                    values[attribute],
                    kind="video",
                    origin=f"telegram:{attribute}",
                    score=82,
                )
        for attribute in _IMAGE_ATTRIBUTE_NAMES:
            if values.get(attribute):
                self._append(
                    values[attribute],
                    kind="image",
                    origin=f"telegram:{attribute}",
                    score=80,
                )


def extract_embedded_media(html: str, page_url: str, source_label: str = "") -> list[MediaCandidate]:
    parser = _EmbeddedMediaParser(page_url, source_label)
    parser.feed(str(html or ""))
    return deduplicate_media_candidates(parser.items)
