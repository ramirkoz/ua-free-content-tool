from __future__ import annotations

import inspect
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from content_agent.models import Article, NewsGroup
from content_agent.network import HttpResponse
from content_agent.news_logic import extract_trend_queries
from content_agent.scheduling import KYIV
from content_agent.trends import threads_keyword_sample
from content_agent.ui.main_window import MainWindow


def _group() -> NewsGroup:
    now = datetime.now(KYIV).isoformat()
    articles = [
        Article(
            id=1,
            source_id=1,
            title="По данным разведки, после выборов в Госдуму 21 сентября Путин планирует усилить мобилизацию, — Зеленский",
            url="https://example.com/1",
            raw_text="Первый источник сообщает о планах усилить мобилизацию.",
            status="new",
            discovered_at=now,
            published_at=now,
        ),
        Article(
            id=2,
            source_id=2,
            title="Путин готовит скрытую мобилизацию сразу после выборов",
            url="https://example.com/2",
            raw_text="Второй источник добавляет детали.",
            status="new",
            discovered_at=now,
            published_at=now,
        ),
    ]
    return NewsGroup(
        id=75,
        canonical_title=articles[0].title,
        status="draft",
        created_at=now,
        updated_at=now,
        source_count=2,
        articles=articles,
    )


def test_threads_queries_are_short_specific_and_have_fallbacks() -> None:
    queries = extract_trend_queries(_group())
    assert queries[0] == "Путин мобилизация"
    assert "Путин" in queries
    assert "мобилизация" in queries
    assert len(queries) <= 4
    assert all(len(query.split()) <= 2 for query in queries)


def test_threads_sample_searches_multiple_queries_and_today_window(monkeypatch) -> None:
    calls: list[str] = []

    def fake_fetch(url: str, **_kwargs) -> HttpResponse:
        calls.append(url)
        params = parse_qs(urlparse(url).query)
        query = params["q"][0]
        search_type = params["search_type"][0]
        ids = {
            ("Путин мобилизация", "RECENT"): ["1", "2"],
            ("Путин мобилизация", "TOP"): ["2", "3"],
            ("Путин", "RECENT"): ["1", "4"],
            ("Путин", "TOP"): ["4", "5"],
        }.get((query, search_type), [])
        body = ("{\"data\":[" + ",".join(f'{{\"id\":\"{item}\"}}' for item in ids) + "]}").encode()
        return HttpResponse(200, {"content-type": "application/json"}, body, url)

    monkeypatch.setattr("content_agent.trends.fetch_url", fake_fetch)
    now = datetime.now(KYIV)
    sample = threads_keyword_sample(
        "token",
        ["Путин мобилизация", "Путин"],
        since=now.replace(hour=0, minute=0, second=0, microsecond=0),
        until=now,
    )
    assert sample.count == 5
    assert sample.per_query == {"Путин мобилизация": 3, "Путин": 3}
    assert len(calls) == 4
    for call in calls:
        params = parse_qs(urlparse(call).query)
        assert params["search_mode"] == ["KEYWORD"]
        assert "since" in params and "until" in params
        assert params["limit"] == ["50"]


def test_threads_sample_distinguishes_zero_from_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "content_agent.trends.fetch_url",
        lambda url, **_kwargs: HttpResponse(200, {"content-type": "application/json"}, b'{"data":[]}', url),
    )
    sample = threads_keyword_sample("token", ["дуже рідкісна тема"])
    assert sample.count == 0
    assert sample.available is True
    assert sample.per_query == {"дуже рідкісна тема": 0}


def test_editor_keeps_publication_controls_fixed_and_has_visible_activity() -> None:
    source = inspect.getsource(MainWindow._build_editor_tab)
    run_source = inspect.getsource(MainWindow.run_async)
    init_source = inspect.getsource(MainWindow.__init__)
    assert 'queue_bar.pack(side="bottom"' in source
    assert "СХВАЛИТИ Й ПОСТАВИТИ В ЧЕРГУ" in source
    assert "Усі доступні" in source and "Очистити" in source and "Публікація" in source
    assert "_adapt_editor_layout" in source
    assert "operation_progress" in init_source
    assert "operation_detail_var" in init_source
    assert "label:" in run_source and "done_label:" in run_source
