from __future__ import annotations

import time

from content_agent.global_duplicates_v1_2_2_rc7 import (
    _canonical_integer_token,
    _fast_candidate_edges,
)
from content_agent.models import NewsGroup


def _group(group_id: int, title: str, body: str) -> NewsGroup:
    now = "2026-09-25T17:00:00+03:00"
    return NewsGroup(
        id=group_id,
        canonical_title=title,
        headline=title,
        combined_text=body,
        status="new",
        source_count=1,
        created_at=now,
        updated_at=now,
        last_published_at=now,
    )


def test_unicode_digit_tokens_are_canonicalized() -> None:
    assert _canonical_integer_token("¹⁹") == "19"
    assert _canonical_integer_token("１２") == "12"
    assert _canonical_integer_token("19") == "19"
    assert _canonical_integer_token("19•") is None


def test_active_global_prefilter_does_not_crash_on_unicode_digits() -> None:
    groups = [
        _group(1, "Подія ¹⁹ вересня у Запоріжжі", "Подія сталася ¹⁹ вересня."),
        _group(2, "Подія 19 вересня у Запоріжжі", "Подія сталася 19 вересня."),
    ]
    edges = _fast_candidate_edges(groups, deadline=time.monotonic() + 5)
    assert isinstance(edges, list)
