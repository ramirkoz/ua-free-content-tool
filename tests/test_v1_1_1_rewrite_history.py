from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from content_agent.config import AppConfig
from content_agent.database import Database
from content_agent.models import CollectedArticle
from content_agent.network import HttpResponse
from content_agent.ollama_client import OllamaError, _decode_rewrite_payload
from content_agent.publication_metrics import collect_publication_metrics

UTC = timezone.utc


def _db_with_story(tmp_path: Path) -> tuple[Database, int, int]:
    db = Database(tmp_path / "history.sqlite3")
    source_id = db.add_source("rss", "Test", "https://example.com/feed")
    db.insert_collected(
        source_id,
        [CollectedArticle("one", "Сирий заголовок", "https://example.com/one", "Текст джерела", datetime.now(UTC).isoformat())],
        enforce_today=False,
    )
    group_id = db.list_groups()[0].id
    db.save_group_rewrite(
        group_id,
        headline="Рерайчений заголовок",
        fact_card="Факти",
        rewrite_text="Готовий текст публікації.",
        platform_texts={"telegram": "Готовий текст публікації."},
    )
    return db, group_id, db.lead_article_id(group_id)


def test_truncated_model_json_is_recovered_without_leaking_object() -> None:
    payload = _decode_rewrite_payload(
        '{\n"headline": "Заголовок",\n"fact_card": "Короткі факти",\n'
        '"rewrite": "Перший абзац.\\n\\nДругий абзац.'
    )
    assert payload["headline"] == "Заголовок"
    assert payload["fact_card"] == "Короткі факти"
    assert payload["rewrite"] == "Перший абзац.\n\nДругий абзац."
    assert not str(payload["rewrite"]).lstrip().startswith("{")


def test_unusable_jsonish_response_fails_closed() -> None:
    with pytest.raises(OllamaError, match="сирий JSON не збережено"):
        _decode_rewrite_payload('{"headline": "Є заголовок", "fact_card": "Є факти", "rewrite": ')


def test_old_approved_story_moves_out_of_inbox_but_remains_in_history(tmp_path: Path) -> None:
    db, group_id, article_id = _db_with_story(tmp_path)
    batch_id = db.create_batch(
        article_id,
        (datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
        {"telegram": "Готовий текст публікації."},
    )
    batch = db.claim_due_batch(owner="worker")
    assert batch and batch.id == batch_id
    db.mark_target_sent(batch.targets[0].id, "101")
    assert db.finish_batch(batch_id, "worker")
    old = (datetime.now(UTC) - timedelta(days=2)).isoformat(timespec="seconds")
    with db.connect() as connection:
        connection.execute("UPDATE news_groups SET updated_at=? WHERE id=?", (old, group_id))

    assert all(group.id != group_id for group in db.list_groups())
    assert all(group.id != group_id for group in db.list_groups(status="approved"))
    history = db.list_publication_history()
    assert len(history) == 1
    assert history[0]["headline"] == "Рерайчений заголовок"
    assert history[0]["targets"][0]["platform"] == "telegram"


def test_exclusions_can_be_deactivated_individually_or_all_at_once(tmp_path: Path) -> None:
    db, group_id, _article_id = _db_with_story(tmp_path)
    assert db.remember_content_exclusions([group_id]) == 1
    rows = db.list_content_exclusions()
    assert len(rows) == 1
    assert db.deactivate_content_exclusions([int(rows[0]["id"])]) == 1
    assert db.content_exclusion_count() == 0

    db.set_group_status(group_id, "new")
    assert db.remember_content_exclusions([group_id]) == 1
    assert db.content_exclusion_count() == 1
    assert db.clear_content_exclusions() == 1
    assert db.content_exclusion_count() == 0
    assert db.list_content_exclusions(active_only=False)


def test_history_metrics_do_not_change_publication_timestamp(tmp_path: Path) -> None:
    db, _group_id, article_id = _db_with_story(tmp_path)
    batch_id = db.create_batch(
        article_id,
        (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        {"telegram": "Готовий текст"},
    )
    batch = db.claim_due_batch(owner="worker")
    assert batch
    target_id = batch.targets[0].id
    db.mark_target_sent(target_id, "42")
    before = db.list_publication_history()[0]["published_at"]
    db.save_publication_metrics(
        target_id,
        metrics={"views": 10, "likes": 3},
        checked_at="2026-08-05T12:00:00+00:00",
        permalink_url="https://t.me/test/42",
    )
    after = db.list_publication_history()[0]
    assert after["published_at"] == before
    assert after["targets"][0]["progress"]["metrics"] == {"likes": 3, "views": 10}


def test_facebook_metrics_parse_reactions_comments_and_shares(monkeypatch) -> None:
    from content_agent import publication_metrics

    def fake_fetch(url: str, **_kwargs: object) -> HttpResponse:
        body = json.dumps(
            {
                "permalink_url": "https://facebook.example/post",
                "reactions": {"summary": {"total_count": 12}},
                "comments": {"summary": {"total_count": 4}},
                "shares": {"count": 3},
            }
        ).encode()
        return HttpResponse(200, {"content-type": "application/json"}, body, url)

    monkeypatch.setattr(publication_metrics, "fetch_url", fake_fetch)
    config = AppConfig(
        facebook_pages=[{"id": "11", "name": "Page", "access_token": "token"}],
        meta_graph_version="v26.0",
    )
    result = collect_publication_metrics(config, "facebook:11", "11_99", {})
    assert result.metrics == {"likes": 12, "comments": 4, "shares": 3}
    assert result.permalink_url == "https://facebook.example/post"


def test_telegram_history_stores_permalink_and_explains_metric_limit() -> None:
    result = collect_publication_metrics(
        AppConfig(telegram_chat_id="@uafree_org"),
        "telegram",
        "77",
        {"remote_ids": [76, 77]},
    )
    assert result.permalink_url == "https://t.me/uafree_org/77"
    assert "Bot API" in result.note


def test_ui_places_history_before_settings_and_exposes_exclusion_manager() -> None:
    source = Path("content_agent/ui/main_window.py").read_text(encoding="utf-8")
    assert source.index("self._build_history_tab()") < source.index("self._build_settings_tab()")
    assert 'text="Історія публікацій"' in source
    assert 'text="Керувати виключеннями"' in source
    assert "refresh_selected_history_metrics" in source
