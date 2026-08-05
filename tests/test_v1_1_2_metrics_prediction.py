from __future__ import annotations

from datetime import datetime
from pathlib import Path

from content_agent.config import AppConfig
from content_agent.models import NewsGroup
from content_agent.performance_prediction import predict_historical_performance
from content_agent.publication_metrics import MetricsResult, collect_all_publication_metrics
from content_agent.scheduling import KYIV


def _history_row(
    batch_id: int,
    group_id: int,
    title: str,
    text: str,
    *,
    views: int,
    likes: int,
    shares: int,
    comments: int,
    platform: str = "threads",
) -> dict[str, object]:
    return {
        "batch_id": batch_id,
        "group_id": group_id,
        "headline": title,
        "rewrite_text": text,
        "published_at": "2026-08-01T10:00:00+03:00",
        "targets": [
            {
                "id": batch_id * 10,
                "platform": platform,
                "status": "sent",
                "remote_id": str(batch_id),
                "progress": {
                    "metrics": {
                        "views": views,
                        "likes": likes,
                        "shares": shares,
                        "comments": comments,
                    },
                    "metrics_checked_at": "2026-08-02T10:00:00+03:00",
                },
            }
        ],
    }


def test_historical_prediction_uses_similar_high_performing_posts() -> None:
    group = NewsGroup(
        id=999,
        canonical_title="Російська атака дронами на Київ: є постраждалі",
        status="draft",
        created_at="2026-08-05T10:00:00+03:00",
        updated_at="2026-08-05T10:00:00+03:00",
        rewrite_text="У Києві після російської атаки дронами пошкоджені будинки та є постраждалі.",
    )
    rows = [
        _history_row(
            index,
            index,
            f"Російська атака дронами на Київ, повідомлено про постраждалих {index}",
            "Унаслідок атаки дронів у Києві пошкоджені будинки, працюють рятувальники.",
            views=900 + index * 30,
            likes=45 + index,
            shares=18 + index,
            comments=12 + index,
        )
        for index in range(1, 7)
    ]
    rows.extend(
        [
            _history_row(
                20 + index,
                20 + index,
                f"Огляд корпоративного навчання та офісних процесів {index}",
                "Компанія представила внутрішній курс для працівників.",
                views=40 + index,
                likes=1,
                shares=0,
                comments=0,
            )
            for index in range(1, 5)
        ]
    )

    result = predict_historical_performance(
        group,
        rows,
        now=datetime(2026, 8, 5, 11, 0, tzinfo=KYIV),
    )

    assert result.available is True
    assert result.sample_size == 10
    assert result.comparable_count >= 5
    assert result.score >= 65
    assert result.confidence >= 45
    assert result.platform_scores["threads"] >= 65
    assert result.top_matches


def test_historical_prediction_does_not_fake_confidence_without_metrics() -> None:
    group = NewsGroup(
        id=10,
        canonical_title="Нова тема",
        status="draft",
        created_at="2026-08-05T10:00:00+03:00",
        updated_at="2026-08-05T10:00:00+03:00",
    )
    rows = [_history_row(1, 1, "Тема", "Текст", views=10, likes=1, shares=0, comments=0)]
    result = predict_historical_performance(group, rows)
    assert result.available is False
    assert result.sample_size == 1
    assert "щонайменше 5" in result.note


def test_bulk_metrics_refresh_uses_platform_circuit_breaker() -> None:
    class FakeDatabase:
        def __init__(self) -> None:
            self.saved: list[tuple[int, dict[str, object]]] = []

        def save_publication_metrics(self, target_id: int, **kwargs: object) -> None:
            self.saved.append((target_id, kwargs))

    rows = [
        {
            "targets": [
                {
                    "id": index,
                    "platform": "facebook:page",
                    "status": "sent",
                    "remote_id": str(index),
                    "progress": {},
                }
            ]
        }
        for index in range(1, 5)
    ]
    rows.append(
        {
            "targets": [
                {
                    "id": 10,
                    "platform": "threads",
                    "status": "sent",
                    "remote_id": "10",
                    "progress": {},
                }
            ]
        }
    )

    calls: list[str] = []

    def collector(_config: AppConfig, platform: str, _remote: str | None, _progress: dict[str, object] | None) -> MetricsResult:
        calls.append(platform)
        if platform.startswith("facebook"):
            return MetricsResult(error="Facebook: Name or service not known")
        return MetricsResult(metrics={"views": 100, "likes": 5})

    db = FakeDatabase()
    summary = collect_all_publication_metrics(
        db,
        AppConfig(),
        rows,
        delay_seconds=0,
        collector=collector,
    )

    assert summary.targets_total == 5
    assert summary.targets_processed == 5
    assert summary.errors == 2
    assert summary.skipped == 2
    assert summary.metrics_received == 1
    assert calls.count("facebook:page") == 2
    assert calls.count("threads") == 1
    assert len(db.saved) == 5


def test_v112_ui_exposes_bulk_refresh_and_historical_prediction() -> None:
    source = (Path(__file__).parents[1] / "content_agent" / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert 'text="Оновити всю статистику"' in source
    assert "def refresh_all_history_metrics(self) -> None:" in source
    assert "predict_historical_performance" in source
    assert 'text="Оцінити потенціал"' in source


def test_failed_refresh_preserves_previous_metrics(tmp_path: Path) -> None:
    from datetime import timedelta, timezone

    from content_agent.database import Database
    from content_agent.models import CollectedArticle

    db = Database(tmp_path / "metrics.sqlite3")
    source_id = db.add_source("rss", "Source", "https://example.com/feed")
    db.insert_collected(
        source_id,
        [CollectedArticle("one", "Headline", "https://example.com/one", "Body", None)],
        enforce_today=False,
    )
    article_id = db.list_articles()[0].id
    batch_id = db.create_batch(
        article_id,
        (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        {"threads": "Text"},
    )
    batch = db.claim_due_batch(owner="worker")
    assert batch and batch.id == batch_id
    target_id = batch.targets[0].id
    db.mark_target_sent(target_id, "remote")
    db.save_publication_metrics(target_id, metrics={"views": 100, "likes": 5})
    db.save_publication_metrics(target_id, metrics=None, error="temporary network error")
    target = db.list_publication_history()[0]["targets"][0]
    assert target["progress"]["metrics"] == {"likes": 5, "views": 100}
    assert target["progress"]["metrics_error"] == "temporary network error"
