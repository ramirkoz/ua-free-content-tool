from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from content_agent.config import AppConfig
from content_agent.database import Database as LegacyDatabase
from content_agent.database_v1_4 import Database
from content_agent.destinations_v1_4 import (
    DestinationSchedule,
    DestinationScheduleStore,
    InstagramDestination,
    destination_ready,
    load_instagram_catalog,
    make_display_title,
    save_instagram_catalog,
)
from content_agent.models import CollectedArticle


UTC = timezone.utc


def add_article(db) -> int:
    source_id = db.add_source("rss", "Test", "https://example.com/feed")
    inserted = db.insert_collected(
        source_id,
        [CollectedArticle("id-1", "Incoming RSS title", "https://example.com/a", "Source body", None)],
        enforce_today=False,
    )
    assert inserted == 1
    article_id = db.list_articles()[0].id
    db.save_rewrite(
        article_id,
        headline="Наша нормальна назва",
        fact_card="Facts",
        rewrite_text="Перший абзац нашого матеріалу.\n\nДругий абзац.",
        platform_texts={},
    )
    return article_id


def schedule(minutes: int) -> str:
    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def test_display_title_never_needs_incoming_source_title() -> None:
    assert make_display_title("Наша назва", "Інший текст") == "Наша назва"
    assert make_display_title("", "Перший наш абзац.\n\nДругий.") == "Перший наш абзац."
    long = make_display_title("", "x" * 500)
    assert len(long) == 140
    assert long.endswith("…")


def test_instagram_catalog_contains_no_tokens_and_resolves_page_secret(tmp_path: Path, isolated_data) -> None:
    row = InstagramDestination(
        id="17841452929006483",
        username="volunteer",
        page_id="103653238987372",
        page_name="Volunteer Page",
    )
    path = tmp_path / "catalog.json"
    save_instagram_catalog([row], path)
    raw = path.read_text(encoding="utf-8")
    assert "access_token" not in raw
    assert load_instagram_catalog(path) == [row]

    save_instagram_catalog([row])
    config = AppConfig(
        instagram_enabled=True,
        facebook_enabled=True,
        facebook_pages=[
            {"id": "103653238987372", "name": "Volunteer Page", "access_token": "secret-page-token"}
        ],
    )
    assert destination_ready(config, row.key) is True


def test_destination_schedule_store_is_independent(tmp_path: Path) -> None:
    config = AppConfig(publish_start_hour=8, publish_end_hour=20, publish_interval_minutes=60)
    store = DestinationScheduleStore(config, tmp_path / "schedules.json")
    assert store.get("telegram") == DestinationSchedule(8, 20, 60)
    store.set("telegram", DestinationSchedule(8, 20, 60))
    store.set("facebook:1", DestinationSchedule(9, 18, 120))
    store.save()
    restored = DestinationScheduleStore(config, tmp_path / "schedules.json")
    assert restored.get("telegram") == DestinationSchedule(8, 20, 60)
    assert restored.get("facebook:1") == DestinationSchedule(9, 18, 120)


def test_one_story_creates_one_batch_per_destination(tmp_path: Path) -> None:
    db = Database(tmp_path / "content.sqlite3")
    article_id = add_article(db)
    result = db.queue_independent_targets(
        article_id,
        {"facebook:1": "fb", "telegram": "tg"},
        {"facebook:1": schedule(60), "telegram": schedule(120)},
        display_title="Наша нормальна назва",
    )
    assert set(result.batch_ids) == {"facebook:1", "telegram"}
    assert len(set(result.batch_ids.values())) == 2
    batches = {batch.id: batch for batch in db.list_batches(limit=20)}
    for key, batch_id in result.batch_ids.items():
        batch = batches[batch_id]
        assert len(batch.targets) == 1
        assert batch.targets[0].platform == key
        assert batch.targets[0].progress["display_title"] == "Наша нормальна назва"


def test_destination_clocks_do_not_consume_each_others_slots(tmp_path: Path) -> None:
    db = Database(tmp_path / "content.sqlite3")
    article_id = add_article(db)
    first = db.queue_independent_targets(
        article_id,
        {"facebook:1": "fb"},
        {"facebook:1": schedule(60)},
        display_title="One",
    )
    fb_latest = db.latest_scheduled_for_target("facebook:1")
    assert fb_latest == first.scheduled_at["facebook:1"]
    assert db.latest_scheduled_for_target("telegram") is None

    source_id = db.add_source("rss", "Test 2", "https://example.com/feed2")
    assert db.insert_collected(
        source_id,
        [CollectedArticle("id-2", "Incoming 2", "https://example.com/b", "Body 2", None)],
        enforce_today=False,
    ) == 1
    article2 = next(article.id for article in db.list_articles() if article.title == "Incoming 2")
    second = db.queue_independent_targets(
        article2,
        {"telegram": "tg"},
        {"telegram": schedule(30)},
        display_title="Two",
    )
    assert db.latest_scheduled_for_target("telegram") == second.scheduled_at["telegram"]
    assert db.latest_scheduled_for_target("facebook:1") == fb_latest


def test_failed_publication_is_terminal_history_not_retry(tmp_path: Path) -> None:
    db = Database(tmp_path / "content.sqlite3")
    article_id = add_article(db)
    result = db.queue_independent_targets(
        article_id,
        {"threads": "thread text"},
        {"threads": schedule(-1)},
        display_title="Наша назва для історії",
    )
    batch = db.claim_due_batch(owner="worker", lease_seconds=60)
    assert batch and batch.id == result.batch_ids["threads"]
    db.mark_target_failed(batch.targets[0].id, "Meta returned an ambiguous error")
    assert db.finish_batch(batch.id, "worker") is True
    assert db.get_batch(batch.id).status == "completed"
    assert db.claim_due_batch(owner="retry") is None
    history = db.list_publication_history(limit=20)
    row = next(item for item in history if item["batch_id"] == batch.id)
    assert row["display_title"] == "Наша назва для історії"
    assert row["targets"][0]["status"] == "failed"
    assert "ambiguous" in row["targets"][0]["last_error"]


def test_shared_media_waits_for_all_destinations_even_after_error(tmp_path: Path) -> None:
    db = Database(tmp_path / "content.sqlite3")
    article_id = add_article(db)
    group_id = db.group_id_for_article(article_id)
    db.set_group_media(
        group_id,
        drive_url="https://drive.google.com/file/d/test/view",
        file_id="test",
        name="photo.jpg",
        kind="image",
        mime="image/jpeg",
        size=10,
    )
    db.queue_independent_targets(
        article_id,
        {"facebook:1": "fb", "telegram": "tg"},
        {"facebook:1": schedule(-2), "telegram": schedule(-1)},
        display_title="Media story",
    )
    assert db.media_cleanup_ready_for_group(group_id) is False

    first = db.claim_due_batch(owner="one")
    assert first is not None
    db.mark_target_sent(first.targets[0].id, "remote")
    assert db.finish_batch(first.id, "one") is True
    assert db.media_cleanup_ready_for_group(group_id) is False

    second = db.claim_due_batch(owner="two")
    assert second is not None
    db.mark_target_failed(second.targets[0].id, "terminal")
    assert db.finish_batch(second.id, "two") is True
    assert db.media_cleanup_ready_for_group(group_id) is True


def test_old_active_multi_target_batch_is_split_on_v14_startup(tmp_path: Path) -> None:
    path = tmp_path / "content.sqlite3"
    legacy = LegacyDatabase(path)
    article_id = add_article(legacy)
    old_batch = legacy.create_batch(
        article_id,
        schedule(60),
        {"facebook:1": "fb", "telegram": "tg"},
    )
    assert len(legacy.get_batch(old_batch).targets) == 2

    upgraded = Database(path)
    assert upgraded.get_batch(old_batch).status == "cancelled"
    active = upgraded.list_batches(limit=20, statuses={"pending"})
    assert len(active) == 2
    assert {batch.targets[0].platform for batch in active} == {"facebook:1", "telegram"}
    assert all(len(batch.targets) == 1 for batch in active)
