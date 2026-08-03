from __future__ import annotations

import pytest

from content_agent.publication_text import (
    FUND_FOOTER,
    THREADS_FUND_FOOTER,
    TextLimitError,
    compose_publication_text,
    telegram_split,
    validate_text,
)


def test_fundraiser_footer_is_always_added() -> None:
    assert compose_publication_text("Новина", "facebook", include_source_link=False, source_url="").endswith(FUND_FOOTER)
    assert compose_publication_text("Новина", "threads", include_source_link=False, source_url="").endswith(THREADS_FUND_FOOTER)


def test_source_link_is_optional_and_off_when_requested() -> None:
    without = compose_publication_text(
        "Новина", "facebook", include_source_link=False, source_url="https://example.com/source"
    )
    with_source = compose_publication_text(
        "Новина", "facebook", include_source_link=True, source_url="https://example.com/source"
    )
    assert "Джерело:" not in without
    assert "Джерело: https://example.com/source" in with_source


def test_threads_overflow_becomes_reply_chain_without_truncation() -> None:
    text = "x" * 501
    validate_text(text, "threads")
    from content_agent.publication_text import metrics_for
    metric = metrics_for(text, "threads")
    assert metric.valid is True
    assert metric.parts == 2


def test_telegram_splits_on_paragraphs_without_losing_text() -> None:
    text = ("Перший абзац.\n\n" + "a" * 3500 + "\n\n" + "Другий абзац. " * 100)
    parts = telegram_split(text)
    assert all(len(part) <= 4096 for part in parts)
    assert "".join("".join(parts).split()) == "".join(text.split())
