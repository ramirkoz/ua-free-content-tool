from __future__ import annotations

from .models import Article, NewsGroup


def source_values_rc3(article: Article | NewsGroup) -> tuple[str, str, str, bool, int]:
    title = str(
        getattr(article, "canonical_title", "")
        or getattr(article, "title", "")
        or "Новина"
    ).strip()
    source_url = str(
        getattr(article, "primary_url", "")
        or getattr(article, "url", "")
        or ""
    ).strip()
    articles = getattr(article, "articles", None)
    clean_parts: list[str] = []
    if isinstance(articles, list):
        clean_parts = [
            str(getattr(item, "raw_text", "") or "").strip()
            for item in articles
            if str(getattr(item, "raw_text", "") or "").strip()
        ]
    source_text = "\n\n".join(clean_parts)
    if not source_text:
        source_text = str(
            getattr(article, "raw_text", "")
            or getattr(article, "combined_text", "")
            or ""
        ).strip()
    include_source = bool(getattr(article, "include_source_link", False))
    total_sources = int(getattr(article, "source_count", 1) or 1)
    return title, source_url, source_text, include_source, total_sources
