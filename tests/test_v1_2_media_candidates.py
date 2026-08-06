from __future__ import annotations

import pytest

from content_agent.media_candidates import (
    MediaCandidate,
    MediaCandidateError,
    deduplicate_media_candidates,
    extract_html_media,
    sniff_media_type,
    validate_media_bytes,
)


def test_html_extraction_prefers_metadata_and_filters_noise() -> None:
    html = """
    <html><head>
      <meta property="og:image" content="/hero.jpg">
      <meta property="og:video" content="https://cdn.example/video.mp4">
    </head><body>
      <img src="/logo.png" width="600" height="600">
      <img src="/small.jpg" width="80" height="80">
      <img src="/hero.jpg" width="1200" height="800">
    </body></html>
    """
    items = extract_html_media(html, "https://news.example/story", "News")
    assert [item.url for item in items] == [
        "https://news.example/hero.jpg",
        "https://cdn.example/video.mp4",
    ]
    assert items[0].origin == "og:image"


def test_jsonld_media_and_relative_urls_are_supported() -> None:
    html = """
    <script type="application/ld+json">
      {"@type":"VideoObject","contentUrl":"/clip.mp4","thumbnailUrl":"/thumb.webp"}
    </script>
    """
    items = extract_html_media(html, "https://example.org/a", "A")
    assert {item.url for item in items} == {
        "https://example.org/clip.mp4",
        "https://example.org/thumb.webp",
    }
    assert {item.kind for item in items} == {"image", "video"}


def test_deduplication_prefers_stronger_candidate() -> None:
    weak = MediaCandidate("https://x/a.jpg", "image", "s", "img", score=10)
    strong = MediaCandidate("https://x/a.jpg", "image", "s", "og", score=100)
    assert deduplicate_media_candidates([weak, strong]) == [strong]


def test_signature_sniffing_and_validation() -> None:
    assert sniff_media_type(b"\xff\xd8\xffx") == ("image", "image/jpeg")
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 20
    result = validate_media_bytes(png, "image/png", source_url="https://x/a.png")
    assert result.kind == "image"
    assert result.mime_type == "image/png"
    assert result.source_url == "https://x/a.png"


def test_validation_rejects_html_and_declared_type_mismatch() -> None:
    with pytest.raises(MediaCandidateError, match="HTML"):
        validate_media_bytes(b"<!doctype html><html>")
    with pytest.raises(MediaCandidateError, match="зображення"):
        validate_media_bytes(b"0000ftypisomxxxx", "image/jpeg")
