from __future__ import annotations

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

from .network import NetworkError, fetch_url

MAX_MEDIA_BYTES = 200 * 1024 * 1024
_MIN_IMAGE_SIDE = 180
_BLOCKED_URL_WORDS = {
    "favicon",
    "sprite",
    "logo",
    "avatar",
    "icon",
    "emoji",
    "pixel",
    "tracker",
    "tracking",
    "badge",
    "spacer",
}
_IMAGE_META_KEYS = {
    "og:image",
    "og:image:url",
    "og:image:secure_url",
    "twitter:image",
    "twitter:image:src",
}
_VIDEO_META_KEYS = {
    "og:video",
    "og:video:url",
    "og:video:secure_url",
    "twitter:player:stream",
}


class MediaCandidateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MediaCandidate:
    url: str
    kind: str
    source_label: str
    origin: str
    mime_hint: str = ""
    width: int = 0
    height: int = 0
    score: int = 0


@dataclass(frozen=True, slots=True)
class ValidatedMedia:
    data: bytes
    kind: str
    mime_type: str
    source_url: str
    size: int


def _integer(value: str | None) -> int:
    try:
        return max(0, int(str(value or "").strip()))
    except ValueError:
        return 0


def _canonical_http_url(base_url: str, value: str) -> str:
    raw = str(value or "").strip()
    if not raw or raw.startswith(("data:", "blob:", "javascript:", "mailto:")):
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
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _looks_like_noise(url: str) -> bool:
    text = url.casefold()
    return any(word in text for word in _BLOCKED_URL_WORDS)


def _guess_kind(url: str, mime_hint: str = "", fallback: str = "image") -> str:
    mime = mime_hint.casefold().split(";", 1)[0].strip()
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "image"
    path = urlsplit(url).path.casefold()
    if path.endswith((".mp4", ".webm", ".mov", ".m4v")):
        return "video"
    if path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return "image"
    return fallback


def _candidate(
    base_url: str,
    value: str,
    *,
    source_label: str,
    origin: str,
    kind: str,
    mime_hint: str = "",
    width: int = 0,
    height: int = 0,
    score: int = 0,
) -> MediaCandidate | None:
    url = _canonical_http_url(base_url, value)
    if not url or _looks_like_noise(url):
        return None
    if kind == "image" and width and height and min(width, height) < _MIN_IMAGE_SIDE:
        return None
    return MediaCandidate(
        url=url,
        kind=_guess_kind(url, mime_hint, kind),
        source_label=source_label,
        origin=origin,
        mime_hint=mime_hint.split(";", 1)[0].strip().casefold(),
        width=width,
        height=height,
        score=score,
    )


def _jsonld_values(payload: object) -> Iterable[tuple[str, str]]:
    if isinstance(payload, list):
        for item in payload:
            yield from _jsonld_values(item)
        return
    if not isinstance(payload, dict):
        return
    for key, value in payload.items():
        lowered = str(key).casefold()
        if lowered in {"image", "thumbnailurl"}:
            if isinstance(value, str):
                yield "image", value
            elif isinstance(value, dict):
                url = value.get("url") or value.get("contentUrl")
                if isinstance(url, str):
                    yield "image", url
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        yield "image", item
                    elif isinstance(item, dict):
                        url = item.get("url") or item.get("contentUrl")
                        if isinstance(url, str):
                            yield "image", url
        elif lowered in {"contenturl", "embedurl"}:
            type_name = str(payload.get("@type") or "").casefold()
            if "video" in type_name and isinstance(value, str):
                yield "video", value
        yield from _jsonld_values(value)


class _MediaHTMLParser(HTMLParser):
    def __init__(self, page_url: str, source_label: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.source_label = source_label
        self.candidates: list[MediaCandidate] = []
        self._jsonld_depth = 0
        self._jsonld_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        values = {str(key).casefold(): str(value or "") for key, value in attrs}
        if tag == "meta":
            key = (values.get("property") or values.get("name") or values.get("itemprop") or "").casefold()
            content = values.get("content", "")
            if key in _IMAGE_META_KEYS:
                item = _candidate(
                    self.page_url,
                    content,
                    source_label=self.source_label,
                    origin=key,
                    kind="image",
                    score=100,
                )
                if item:
                    self.candidates.append(item)
            elif key in _VIDEO_META_KEYS:
                item = _candidate(
                    self.page_url,
                    content,
                    source_label=self.source_label,
                    origin=key,
                    kind="video",
                    score=100,
                )
                if item:
                    self.candidates.append(item)
            return
        if tag == "img":
            src = values.get("src") or values.get("data-src") or values.get("data-original") or values.get("data-lazy-src")
            item = _candidate(
                self.page_url,
                src,
                source_label=self.source_label,
                origin="html:img",
                kind="image",
                width=_integer(values.get("width")),
                height=_integer(values.get("height")),
                score=45,
            )
            if item:
                self.candidates.append(item)
            return
        if tag == "video":
            for key, kind, score in (("poster", "image", 55), ("src", "video", 70)):
                item = _candidate(
                    self.page_url,
                    values.get(key, ""),
                    source_label=self.source_label,
                    origin=f"html:video:{key}",
                    kind=kind,
                    mime_hint=values.get("type", ""),
                    score=score,
                )
                if item:
                    self.candidates.append(item)
            return
        if tag == "source":
            item = _candidate(
                self.page_url,
                values.get("src", ""),
                source_label=self.source_label,
                origin="html:source",
                kind=_guess_kind(values.get("src", ""), values.get("type", ""), "video"),
                mime_hint=values.get("type", ""),
                score=70,
            )
            if item:
                self.candidates.append(item)
            return
        if tag == "script" and values.get("type", "").casefold().split(";", 1)[0].strip() == "application/ld+json":
            self._jsonld_depth = 1
            self._jsonld_chunks = []

    def handle_data(self, data: str) -> None:
        if self._jsonld_depth:
            self._jsonld_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "script" or not self._jsonld_depth:
            return
        self._jsonld_depth = 0
        raw = "".join(self._jsonld_chunks).strip()
        self._jsonld_chunks = []
        if not raw or len(raw) > 1_000_000:
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        for kind, value in _jsonld_values(payload):
            item = _candidate(
                self.page_url,
                value,
                source_label=self.source_label,
                origin="json-ld",
                kind=kind,
                score=65,
            )
            if item:
                self.candidates.append(item)


def deduplicate_media_candidates(candidates: Iterable[MediaCandidate]) -> list[MediaCandidate]:
    best: dict[str, MediaCandidate] = {}
    for item in candidates:
        current = best.get(item.url)
        if current is None or item.score > current.score:
            best[item.url] = item
        elif item.score == current.score and item.width * item.height > current.width * current.height:
            best[item.url] = item
    return sorted(best.values(), key=lambda item: (-item.score, item.kind, item.url.casefold()))


def extract_html_media(html: str, page_url: str, source_label: str = "") -> list[MediaCandidate]:
    parser = _MediaHTMLParser(page_url, source_label)
    parser.feed(str(html or ""))
    return deduplicate_media_candidates(parser.candidates)


def sniff_media_type(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image", "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image", "image/webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "video", "video/mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video", "video/webm"
    return "", ""


def validate_media_bytes(data: bytes, declared_content_type: str = "", *, source_url: str = "") -> ValidatedMedia:
    if not data:
        raise MediaCandidateError("Медіафайл порожній.")
    if len(data) > MAX_MEDIA_BYTES:
        raise MediaCandidateError("Медіафайл перевищує ліміт програми 200 МБ.")
    prefix = data[:512].lstrip().lower()
    if prefix.startswith((b"<!doctype html", b"<html", b"<?xml", b"<script")):
        raise MediaCandidateError("За посиланням отримано HTML або скрипт замість медіафайла.")
    kind, detected = sniff_media_type(data)
    if not kind:
        raise MediaCandidateError("Формат файла не підтримується або не відповідає медіаданим.")
    declared = declared_content_type.split(";", 1)[0].strip().casefold()
    if declared and not declared.startswith(("image/", "video/", "application/octet-stream")):
        raise MediaCandidateError(f"Сервер повернув непідтримуваний Content-Type: {declared}.")
    if declared.startswith("image/") and kind != "image":
        raise MediaCandidateError("Content-Type заявляє зображення, але сигнатура файла інша.")
    if declared.startswith("video/") and kind != "video":
        raise MediaCandidateError("Content-Type заявляє відео, але сигнатура файла інша.")
    return ValidatedMedia(data=data, kind=kind, mime_type=detected, source_url=source_url, size=len(data))


def download_media_candidate(candidate: MediaCandidate) -> ValidatedMedia:
    try:
        response = fetch_url(
            candidate.url,
            headers={"Accept": "image/*,video/*"},
            max_bytes=MAX_MEDIA_BYTES,
            timeout=180,
            max_redirects=5,
        )
    except NetworkError as exc:
        raise MediaCandidateError(str(exc)) from exc
    return validate_media_bytes(
        response.body,
        response.headers.get("content-type", ""),
        source_url=response.final_url,
    )
