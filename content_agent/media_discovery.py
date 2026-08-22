from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urlsplit

from .embedded_media import extract_embedded_media
from .media_candidates import (
    MediaCandidate,
    MediaCandidateError,
    ValidatedMedia,
    deduplicate_media_candidates,
    download_media_candidate,
    extract_html_media,
)
from .network import NetworkError, fetch_url

_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v"}


def candidate_kind_from_url(url: str) -> str:
    suffix = PurePosixPath(urlsplit(str(url or "")).path).suffix.casefold()
    if suffix in _VIDEO_EXTENSIONS:
        return "video"
    return "image"


def direct_media_candidate(url: str, source_label: str = "Вручну додане посилання") -> MediaCandidate:
    parts = urlsplit(str(url or "").strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise MediaCandidateError("Вкажіть абсолютне HTTP/HTTPS-посилання без логіна й пароля.")
    return MediaCandidate(
        url=parts.geturl(),
        kind=candidate_kind_from_url(parts.geturl()),
        source_label=source_label,
        origin="manual:url",
        score=100,
    )


def discover_page_media(url: str, source_label: str = "") -> list[MediaCandidate]:
    try:
        response = fetch_url(
            url,
            headers={"Accept": "text/html,application/xhtml+xml"},
            max_bytes=5 * 1024 * 1024,
            allowed_content_types=_HTML_TYPES,
            timeout=30,
            max_redirects=5,
        )
    except NetworkError as exc:
        raise MediaCandidateError(str(exc)) from exc
    html = response.body.decode("utf-8", errors="replace")
    return deduplicate_media_candidates(
        [
            *extract_html_media(html, response.final_url, source_label),
            *extract_embedded_media(html, response.final_url, source_label),
        ]
    )


def discover_group_media(articles: object) -> list[MediaCandidate]:
    candidates: list[MediaCandidate] = []
    for article in articles if isinstance(articles, (list, tuple)) else []:
        url = str(getattr(article, "url", "") or "").strip()
        if not url:
            continue
        label = str(getattr(article, "source_name", "") or getattr(article, "title", "") or url)
        try:
            candidates.extend(discover_page_media(url, label))
        except MediaCandidateError:
            continue
    return deduplicate_media_candidates(candidates)


def resolve_manual_media_url(
    url: str,
    source_label: str = "Вручну додане посилання",
) -> tuple[ValidatedMedia | None, list[MediaCandidate]]:
    """Resolve a pasted URL as a direct media file or a page with choices."""

    candidate = direct_media_candidate(url, source_label)
    suffix = PurePosixPath(urlsplit(candidate.url).path).suffix.casefold()
    if suffix in _IMAGE_EXTENSIONS | _VIDEO_EXTENSIONS:
        return download_media_candidate(candidate), []

    try:
        page_candidates = discover_page_media(candidate.url, source_label)
    except MediaCandidateError:
        page_candidates = []
    if page_candidates:
        return None, page_candidates
    return download_media_candidate(candidate), []
