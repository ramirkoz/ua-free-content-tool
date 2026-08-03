from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from content_agent.database import Database
from content_agent.models import CollectedArticle

UTC = timezone.utc


def _db_with_article(tmp_path: Path) -> tuple[Database, int, int]:
    db = Database(tmp_path / "fix12.sqlite3")
    source_id = db.add_source("rss", "FIX12", "https://example.com/fix12")
    assert db.insert_collected(
        source_id,
        [CollectedArticle("fix12-1", "FIX12 title", "https://example.com/fix12-1", "FIX12 body", None)],
        enforce_today=False,
    ) == 1
    group = db.list_groups()[0]
    return db, db.lead_article_id(group.id), group.id


def test_rejected_is_hidden_but_still_available_by_filter(tmp_path: Path) -> None:
    db, _article_id, group_id = _db_with_article(tmp_path)
    db.set_group_status(group_id, "rejected")
    assert db.list_groups() == []
    assert [group.id for group in db.list_groups(status="rejected")] == [group_id]


def test_duplicate_only_after_cancelled_partial_history_creates_no_new_batch(tmp_path: Path) -> None:
    db, article_id, _group_id = _db_with_article(tmp_path)
    first = db.queue_targets(article_id, (datetime.now(UTC) - timedelta(seconds=1)).isoformat(), {"telegram": "tg"})
    batch = db.claim_due_batch(owner="worker")
    assert batch
    db.mark_target_sent(batch.targets[0].id, "remote")
    # Simulate a user cancellation after a partial/manual publication state.
    with db.connect() as connection:
        connection.execute(
            "UPDATE publication_batches SET status='pending',lease_owner=NULL,lease_until=NULL WHERE id=?",
            (first.batch_id,),
        )
    db.cancel_batch(first.batch_id)
    before = [item.id for item in db.list_batches()]
    result = db.queue_targets(
        article_id,
        (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        {"telegram": "do not duplicate"},
    )
    after = [item.id for item in db.list_batches()]
    assert result.batch_id == first.batch_id
    assert result.status == "completed"
    assert result.already_sent == ["telegram"]
    assert after == before


def test_all_sent_with_media_stays_active_for_cleanup(tmp_path: Path) -> None:
    db, article_id, group_id = _db_with_article(tmp_path)
    db.set_group_media(
        group_id,
        drive_url="https://drive.google.com/file/d/abc/view",
        file_id="abc",
        name="image.jpg",
        kind="image",
        mime="image/jpeg",
        size=100,
    )
    queued = db.queue_targets(article_id, (datetime.now(UTC) - timedelta(seconds=1)).isoformat(), {"telegram": "tg"})
    batch = db.claim_due_batch(owner="worker")
    assert batch
    db.mark_target_sent(batch.targets[0].id, "remote")
    # Do not call finish_batch: the editor synchronizes after the target is sent,
    # while permanent Drive cleanup still belongs to the worker.
    with db.connect() as connection:
        connection.execute(
            "UPDATE publication_batches SET status='pending',lease_owner=NULL,lease_until=NULL WHERE id=?",
            (queued.batch_id,),
        )
    result = db.queue_targets(article_id, datetime.now(UTC).isoformat(), {"telegram": "tg"})
    assert result.status == "pending"
    assert db.get_batch(queued.batch_id).status == "pending"
    with pytest.raises(ValueError, match="очищення Google Drive"):
        db.cancel_batch(queued.batch_id)


def test_completed_package_cannot_be_cancelled(tmp_path: Path) -> None:
    db, article_id, _group_id = _db_with_article(tmp_path)
    queued = db.queue_targets(article_id, (datetime.now(UTC) - timedelta(seconds=1)).isoformat(), {"telegram": "tg"})
    batch = db.claim_due_batch(owner="worker")
    assert batch
    db.mark_target_sent(batch.targets[0].id, "remote")
    assert db.finish_batch(batch.id, "worker")
    with pytest.raises(ValueError, match="Завершений пакет"):
        db.cancel_batch(queued.batch_id)


def test_fix12_ui_contract_is_present() -> None:
    source = Path(__file__).parents[1] / "content_agent" / "ui" / "main_window.py"
    text = source.read_text(encoding="utf-8")
    assert 'self.group_filter = tk.StringVar(value="Активні")' in text
    assert '"Відхилені": "rejected"' in text
    assert 'self.queue_filter = tk.StringVar(value="Активні")' in text
    assert 'text="Відкрити й редагувати"' in text
    assert 'text="Скасувати / прибрати"' in text
    assert "queue_targets(" in text
