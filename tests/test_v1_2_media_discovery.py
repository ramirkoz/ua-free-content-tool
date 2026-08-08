from __future__ import annotations

from dataclasses import dataclass

import pytest

from content_agent.media_candidates import MediaCandidate, MediaCandidateError, ValidatedMedia
from content_agent.media_discovery import (
    candidate_kind_from_url,
    direct_media_candidate,
    discover_group_media,
    resolve_manual_media_url,
)


@dataclass
class _Article:
    url: str
    source_name: str
    title: str = ""


def test_direct_candidate_validates_url_and_kind() -> None:
    assert candidate_kind_from_url("https://x/a.mp4") == "video"
    assert candidate_kind_from_url("https://x/a.jpg") == "image"
    candidate = direct_media_candidate("https://x/a.webp")
    assert candidate.kind == "image"
    with pytest.raises(MediaCandidateError):
        direct_media_candidate("file:///tmp/a.jpg")


def test_group_discovery_combines_and_deduplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    from content_agent import media_discovery

    def discover(url: str, label: str) -> list[MediaCandidate]:
        return [MediaCandidate("https://cdn/x.jpg", "image", label, "og:image", score=100)]

    monkeypatch.setattr(media_discovery, "discover_page_media", discover)
    items = discover_group_media([
        _Article("https://one/story", "One"),
        _Article("https://two/story", "Two"),
    ])
    assert len(items) == 1
    assert items[0].url == "https://cdn/x.jpg"


def test_manual_url_with_media_extension_downloads_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    from content_agent import media_discovery

    expected = ValidatedMedia(b"data", "image", "image/jpeg", "https://x/a.jpg", 4)
    monkeypatch.setattr(media_discovery, "download_media_candidate", lambda candidate: expected)
    media, candidates = resolve_manual_media_url("https://x/a.jpg")
    assert media == expected
    assert candidates == []


def test_manual_page_returns_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    from content_agent import media_discovery

    found = [MediaCandidate("https://cdn/x.jpg", "image", "Page", "og:image", score=100)]
    monkeypatch.setattr(media_discovery, "discover_page_media", lambda url, label: found)
    media, candidates = resolve_manual_media_url("https://x/story")
    assert media is None
    assert candidates == found
