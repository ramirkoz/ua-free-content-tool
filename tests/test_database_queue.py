from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from content_agent.database import Database, LeaseLost
from content_agent.models import CollectedArticle

UTC = timezone.utc


def build_database(tmp_path: Path) -> Database:
    return Database(tmp_path / "content.sqlite3")


def add_article(db: Database) -> int:
    source_id = db.add_source("rss", "Test", "https://example.com/feed")
    inserted = db.insert_collected(
        source_id,
        [CollectedArticle("id-1", "Title", "https://example.com/a", "Full article text", None)],
        enforce_today=False,
    )
    assert inserted == 1
    assert db.insert_collected(
        source_id,
        [CollectedArticle("id-1", "Title", "https://example.com/a", "Full article text", None)],
        enforce_today=False,
    ) == 0
    return db.list_articles()[0].id


def test_article_dedupe_and_rewrite(tmp_path: Path) -> None:
    db = build_database(tmp_path)
    article_id = add_article(db)
    db.save_rewrite(
        article_id,
        headline="New title",
        fact_card="Facts",
        rewrite_text="Rewrite",
        platform_texts={"facebook": "FB", "telegram": "TG"},
    )
    article = db.get_article(article_id)
    assert article.status == "draft"
    assert article.headline == "New title"
    assert db.get_platform_texts(article_id)["telegram"] == "TG"


def test_two_facebook_targets_are_independent(tmp_path: Path) -> None:
    db = build_database(tmp_path)
    article_id = add_article(db)
    batch_id = db.create_batch(
        article_id,
        (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        {"facebook:1": "one", "facebook:2": "two"},
    )
    batch = db.claim_due_batch(owner="worker")
    assert batch and batch.id == batch_id
    first, second = batch.targets
    db.mark_target_sent(first.id, "remote-1")
    db.mark_target_failed(second.id, "temporary")
    completed = db.finish_batch(batch.id, "worker", retry_minutes=0)
    assert completed is False
    retry = db.claim_due_batch(owner="worker-2")
    assert retry is not None
    statuses = {target.platform: target.status for target in retry.targets}
    assert statuses["facebook:1"] == "sent"
    assert statuses["facebook:2"] == "failed"


def test_lease_loss_stops_writes(tmp_path: Path) -> None:
    db = build_database(tmp_path)
    article_id = add_article(db)
    db.create_batch(
        article_id,
        (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        {"telegram": "payload"},
    )
    batch = db.claim_due_batch(owner="owner", lease_seconds=60)
    assert batch
    with db.connect() as connection:
        connection.execute(
            "UPDATE publication_batches SET lease_owner='other' WHERE id=?",
            (batch.id,),
        )
    with pytest.raises(LeaseLost):
        db.assert_lease(batch.id, "owner")


def test_expired_in_progress_batch_is_reclaimed(tmp_path: Path) -> None:
    db = build_database(tmp_path)
    article_id = add_article(db)
    batch_id = db.create_batch(
        article_id,
        (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        {"telegram": "payload"},
    )
    first = db.claim_due_batch(owner="crashed-worker", lease_seconds=60)
    assert first and first.id == batch_id
    with db.connect() as connection:
        connection.execute(
            "UPDATE publication_batches SET lease_until=? WHERE id=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(timespec="seconds"), batch_id),
        )
    recovered = db.claim_due_batch(owner="recovery-worker", lease_seconds=60)
    assert recovered is not None
    assert recovered.id == batch_id
    assert recovered.lease_owner == "recovery-worker"
    assert recovered.attempts == 2


def test_existing_batch_is_extended_instead_of_rejected(tmp_path: Path) -> None:
    db = build_database(tmp_path)
    article_id = add_article(db)
    scheduled = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    first = db.queue_targets(article_id, scheduled, {"telegram": "payload"})
    second = db.queue_targets(article_id, scheduled, {"telegram": "payload", "facebook:1": "facebook"})
    assert second.batch_id == first.batch_id
    assert second.created is False
    assert second.added == ["facebook:1"]
    batch = db.get_batch(first.batch_id)
    assert {target.platform for target in batch.targets} == {"telegram", "facebook:1"}


def test_pending_target_can_be_removed_by_editor_selection(tmp_path: Path) -> None:
    db = build_database(tmp_path)
    article_id = add_article(db)
    scheduled = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    result = db.queue_targets(
        article_id,
        scheduled,
        {"telegram": "tg", "facebook:1": "fb", "threads": "th"},
    )
    changed = db.queue_targets(article_id, scheduled, {"facebook:1": "fb", "threads": "th"})
    assert changed.batch_id == result.batch_id
    assert changed.removed == ["telegram"]
    assert {target.platform for target in db.get_batch(result.batch_id).targets} == {"facebook:1", "threads"}


def test_sent_target_is_never_removed_or_duplicated(tmp_path: Path) -> None:
    db = build_database(tmp_path)
    article_id = add_article(db)
    scheduled = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    result = db.queue_targets(article_id, scheduled, {"telegram": "tg"})
    batch = db.claim_due_batch(owner="worker")
    assert batch and batch.id == result.batch_id
    db.mark_target_sent(batch.targets[0].id, "remote")
    assert db.finish_batch(batch.id, "worker") is True
    changed = db.queue_targets(
        article_id,
        (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        {"telegram": "new tg", "threads": "th"},
    )
    assert changed.batch_id == result.batch_id
    assert changed.already_sent == ["telegram"]
    assert changed.added == ["threads"]
    statuses = {target.platform: target.status for target in db.get_batch(result.batch_id).targets}
    assert statuses == {"telegram": "sent", "threads": "pending"}


def test_pending_batch_can_be_cancelled_and_hidden_from_active_queue(tmp_path: Path) -> None:
    db = build_database(tmp_path)
    article_id = add_article(db)
    result = db.queue_targets(
        article_id,
        (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        {"telegram": "tg"},
    )
    db.cancel_batch(result.batch_id)
    assert db.get_batch(result.batch_id).status == "cancelled"
    assert db.list_batches(statuses={"pending", "in_progress"}) == []
    assert [batch.id for batch in db.list_batches(statuses={"cancelled"})] == [result.batch_id]
    group = db.get_group(db.group_id_for_article(article_id))
    assert group.status == "draft"


def test_in_progress_batch_cannot_be_edited_or_cancelled(tmp_path: Path) -> None:
    db = build_database(tmp_path)
    article_id = add_article(db)
    db.queue_targets(article_id, (datetime.now(UTC) - timedelta(seconds=1)).isoformat(), {"telegram": "tg"})
    batch = db.claim_due_batch(owner="worker")
    assert batch
    with pytest.raises(ValueError, match="зараз публікується"):
        db.queue_targets(article_id, datetime.now(UTC).isoformat(), {"threads": "th"})
    with pytest.raises(ValueError, match="зараз публікується"):
        db.cancel_batch(batch.id)
