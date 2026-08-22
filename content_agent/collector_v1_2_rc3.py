from __future__ import annotations

from .collectors import _fetch_article_text, collect_source as _base_collect_source, parse_rss
from .media_hint_store_v1_2_rc3 import SourceMediaHintStore
from .models import CollectedArticle, Source
from .network import fetch_url
from .rss_media_hints_v1_2_rc3 import rss_media_hints


def collect_source_rc3(source: Source) -> list[CollectedArticle]:
    """RC3 collector wrapper preserving RSS/Atom media enclosures."""

    if source.kind != "rss":
        return _base_collect_source(source)

    response = fetch_url(
        source.url,
        max_bytes=8 * 1024 * 1024,
        allowed_content_types={
            "application/rss+xml",
            "application/atom+xml",
            "application/xml",
            "text/xml",
        },
    )
    items = parse_rss(response.body)
    hints = rss_media_hints(response.body, source.name)
    store = SourceMediaHintStore()
    for item in items[:15]:
        article_text = _fetch_article_text(item.url)
        if article_text and len(article_text) > len(item.raw_text):
            item.raw_text = article_text
    for item in items:
        found = hints.get(item.url) or hints.get(item.external_id) or []
        if found:
            store.save(item.url, found)
    return items
