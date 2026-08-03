from __future__ import annotations

from datetime import datetime, timedelta

from content_agent.models import Article, NewsGroup
from content_agent.news_logic import (
    belongs_to_group,
    calculate_explosiveness,
    event_similarity,
    is_today_kyiv,
)
from content_agent.scheduling import KYIV


def _article(title: str, text: str, published: str) -> Article:
    return Article(
        id=1,
        source_id=1,
        title=title,
        url="https://example.com/a",
        raw_text=text,
        status="new",
        discovered_at=published,
        published_at=published,
    )


def test_today_filter_uses_kyiv_calendar_day() -> None:
    now = datetime(2026, 7, 25, 0, 15, tzinfo=KYIV)
    assert is_today_kyiv("2026-07-24T21:30:00+00:00", now=now) is True
    assert is_today_kyiv("2026-07-24T20:30:00+00:00", now=now) is False
    assert is_today_kyiv(None, now=now) is False


def test_paraphrased_same_event_is_grouped() -> None:
    published = datetime.now(KYIV).isoformat()
    existing = _article(
        "У Запоріжжі пролунали вибухи",
        "У місті було гучно після атаки дронів.",
        published,
    )
    title = "Росіяни атакували Запоріжжя дронами"
    text = "Ворог завдав удару по обласному центру, пролунали вибухи."
    assert event_similarity(existing.title, existing.raw_text, title, text) >= 0.38
    assert belongs_to_group(title, text, [existing]) is True


def test_unrelated_events_are_not_grouped() -> None:
    published = datetime.now(KYIV).isoformat()
    existing = _article(
        "Зеленський зустрівся з Макроном у Парижі",
        "Президенти обговорили підтримку України.",
        published,
    )
    assert belongs_to_group(
        "У Києві відкрили нову школу",
        "Навчальний заклад прийняв учнів.",
        [existing],
    ) is False


def test_explosiveness_recommends_platforms_without_x() -> None:
    now = datetime.now(KYIV)
    articles = [
        _article(
            "Росіяни атакували Запоріжжя дронами",
            "Є наслідки атаки, працюють рятувальники.",
            (now - timedelta(minutes=index * 4)).isoformat(),
        )
        for index in range(5)
    ]
    group = NewsGroup(
        id=1,
        canonical_title=articles[0].title,
        status="new",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        source_count=len(articles),
        articles=articles,
    )
    score, confidence, details, recommendations = calculate_explosiveness(group, threads_posts=12)
    assert score >= 60
    assert confidence >= 70
    assert details["threads_posts"] == 12
    assert "telegram" in recommendations
    assert "facebook" in recommendations
    assert "threads" in recommendations
    assert all("twitter" not in item and item != "x" for item in recommendations)
