from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from content_agent.database import Database
from content_agent.models import CollectedArticle

UTC = timezone.utc


def _make_batch(db: Database, suffix: str) -> tuple[int, int]:
    source_id = db.add_source("rss", f"FIX21 {suffix}", f"https://example.com/{suffix}.xml")
    inserted = db.insert_collected(
        source_id,
        [
            CollectedArticle(
                f"fix21-{suffix}",
                f"FIX21 {suffix}",
                f"https://example.com/{suffix}",
                f"Body {suffix}",
                None,
            )
        ],
        enforce_today=False,
    )
    assert inserted == 1
    group = next(item for item in db.list_groups() if item.canonical_title == f"FIX21 {suffix}")
    article_id = db.lead_article_id(group.id)
    batch_id = db.create_batch(
        article_id,
        (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        {"telegram": f"Text {suffix}"},
    )
    return batch_id, group.id


def test_fix21_bulk_cancel_cancels_selected_packages(tmp_path: Path) -> None:
    db = Database(tmp_path / "bulk.sqlite3")
    first, first_group = _make_batch(db, "one")
    second, second_group = _make_batch(db, "two")
    third, _third_group = _make_batch(db, "three")

    cancelled = db.cancel_batches([first, second])

    assert cancelled == [first, second]
    assert db.get_batch(first).status == "cancelled"
    assert db.get_batch(second).status == "cancelled"
    assert db.get_batch(third).status == "pending"
    assert db.get_group(first_group).status == "draft"
    assert db.get_group(second_group).status == "draft"


def test_fix21_bulk_cancel_is_atomic_when_one_package_is_busy(tmp_path: Path) -> None:
    db = Database(tmp_path / "atomic.sqlite3")
    first, _first_group = _make_batch(db, "first")
    second, _second_group = _make_batch(db, "second")
    with db.connect() as connection:
        connection.execute(
            "UPDATE publication_batches SET status='in_progress',lease_owner='worker',lease_until=? WHERE id=?",
            ((datetime.now(UTC) + timedelta(minutes=5)).isoformat(), second),
        )

    with pytest.raises(ValueError, match=f"Пакет #{second} зараз публікується"):
        db.cancel_batches([first, second])

    assert db.get_batch(first).status == "pending"
    assert db.get_batch(second).status == "in_progress"


def test_fix21_cancelled_partial_history_keeps_group_approved(tmp_path: Path) -> None:
    db = Database(tmp_path / "partial.sqlite3")
    batch_id, group_id = _make_batch(db, "partial")
    batch = db.get_batch(batch_id)
    db.mark_target_sent(batch.targets[0].id, "remote-id")

    assert db.cancel_batches([batch_id]) == [batch_id]
    assert db.get_batch(batch_id).status == "cancelled"
    assert db.get_group(group_id).status == "approved"


def test_fix21_queue_ui_supports_standard_multi_selection() -> None:
    source = Path(__file__).parents[1] / "content_agent" / "ui" / "main_window.py"
    text = source.read_text(encoding="utf-8")

    assert 'selectmode="extended"' in text
    assert 'text="Скасувати / прибрати"' in text
    assert 'self.queue_tree.bind("<Delete>", self._delete_selected_queue_rows)' in text
    assert 'self.queue_tree.bind("<Control-a>", self._select_all_queue_rows)' in text
    assert "Shift — діапазон" in text
    assert "def _selected_queue_batch_ids(self) -> list[int]:" in text
    assert "self.db.cancel_batches(batch_ids)" in text
