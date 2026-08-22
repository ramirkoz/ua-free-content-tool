from __future__ import annotations

from content_agent.evidence_pack import build_evidence_pack
from content_agent.fact_guard import guard_rewrite
from content_agent.models import Article, NewsGroup


def _many_source_group(count: int) -> NewsGroup:
    articles = []
    for index in range(1, count + 1):
        articles.append(
            Article(
                id=index,
                source_id=index,
                title=f"Матеріал {index}",
                url=f"https://example.com/{index}",
                raw_text=f"Компанія Source{index} повідомила про показник {index * 10} одиниць.",
                status="new",
                published_at="2026-08-18T10:00:00+00:00",
                source_name=f"Source{index}",
            )
        )
    return NewsGroup(
        id=1,
        canonical_title="Великий блок",
        status="new",
        created_at="2026-08-18T10:00:00+00:00",
        updated_at="2026-08-18T10:00:00+00:00",
        source_count=count,
        articles=articles,
    )


def test_evidence_budget_preserves_every_source_fact_after_condensation() -> None:
    group = _many_source_group(24)
    pack = build_evidence_pack(group, max_chars=4300)
    assert len(pack.text) <= 4300
    assert pack.source_count == 24
    assert "УНІКАЛЬНІ ФАКТИ ЗІ ЗВЕДЕНОЇ ГРУПИ" in pack.text
    for index in range(1, 25):
        assert f"Source{index}" in pack.text
        assert f"{index * 10} одиниць" in pack.text


def test_source_timestamp_does_not_authorize_event_year() -> None:
    evidence = """ДЖЕРЕЛО 1/1
НАЗВА: Example
ЗАГОЛОВОК: Компанія представила систему
ЧАС: 2026-08-18T10:00:00+00:00
ТЕКСТ:
Компанія представила систему."""
    result = guard_rewrite(
        evidence,
        "Компанія представила систему",
        "Компанія представила систему у 2026 році.",
        language="uk",
    )
    assert result.allowed is False
    assert "2026" in result.unsupported_numbers
