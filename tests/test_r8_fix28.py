from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from content_agent.database import DATABASE_SCHEMA_VERSION, Database
from content_agent.models import CollectedArticle
from content_agent.publication_text import TELEGRAM_MEDIA_CAPTION_LIMIT, compose_publication_text
from content_agent.ollama_client import OllamaError
from content_agent.queue_migration import (
    QUEUE_900_MIGRATION_KEY,
    QueueMigrationError,
    build_queue_compression_prompt,
    build_target_payloads,
    compress_approved_text,
    effective_editorial_limit,
    scan_queue_for_900_migration,
)

UTC = timezone.utc


def _future_db(tmp_path: Path, *, text: str, include_source: bool = False) -> tuple[Database, int, int]:
    db = Database(tmp_path / "work.sqlite3")
    sid = db.add_source("rss", "Source", "https://example.com/feed")
    db.insert_collected(
        sid,
        [CollectedArticle("x", "Важлива новина", "https://example.com/article", "Факти", None)],
        enforce_today=False,
    )
    group = db.list_groups()[0]
    db.save_group_rewrite(
        group.id,
        headline="Заголовок",
        fact_card="Факти",
        rewrite_text=text,
        platform_texts={platform: text for platform in ("telegram", "threads", "linkedin")},
    )
    db.set_group_options(group.id, include_source_link=include_source)
    db.set_group_media(
        group.id,
        drive_url="https://drive.google.com/file/d/abc/view",
        file_id="abc",
        name="photo.jpg",
        kind="image",
        mime="image/jpeg",
        size=123,
    )
    scheduled = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    payloads = {
        platform: compose_publication_text(
            text,
            platform,
            include_source_link=include_source,
            source_url="https://example.com/article",
        )
        for platform in ("telegram", "threads", "linkedin")
    }
    batch_id = db.create_batch(db.lead_article_id(group.id), scheduled, payloads)
    return db, group.id, batch_id


def test_fix28_schema_is_additive_and_scan_finds_only_future_long_queue(tmp_path: Path) -> None:
    assert DATABASE_SCHEMA_VERSION == 8
    db, group_id, batch_id = _future_db(tmp_path, text=("Факт. " * 220).strip())
    scan = scan_queue_for_900_migration(db)
    assert not scan.blockers
    assert [item.batch_id for item in scan.candidates] == [batch_id]
    candidate = scan.candidates[0]
    assert candidate.group_id == group_id
    assert candidate.limit <= 900
    assert len(candidate.old_text) > candidate.limit
    assert set(candidate.platforms) == {"telegram", "threads", "linkedin"}


def test_fix28_dynamic_limit_keeps_telegram_media_as_one_caption() -> None:
    limit = effective_editorial_limit(
        ["telegram", "threads"],
        include_source_link=True,
        source_url="https://example.com/very/long/source/path",
        has_media=True,
    )
    assert 120 <= limit < 900
    payload = compose_publication_text(
        "Ф" * limit,
        "telegram",
        include_source_link=True,
        source_url="https://example.com/very/long/source/path",
    )
    assert len(payload) <= TELEGRAM_MEDIA_CAPTION_LIMIT


def test_fix28_atomic_apply_changes_only_unsent_texts_and_preserves_queue(tmp_path: Path) -> None:
    db, group_id, batch_id = _future_db(tmp_path, text=("Детальний факт. " * 90).strip())
    before = db.get_batch(batch_id)
    before_schedule = before.scheduled_at
    before_status = before.status
    before_target_ids = [target.id for target in before.targets]
    before_target_statuses = [target.status for target in before.targets]
    before_media = db.get_group(group_id).media_file_id

    candidate = scan_queue_for_900_migration(db).candidates[0]
    new_text = ("Стислий перевірений факт. " * 20).strip()
    assert len(new_text) <= candidate.limit
    update = {
        "batch_id": candidate.batch_id,
        "group_id": candidate.group_id,
        "scheduled_at": candidate.scheduled_at,
        "old_text": candidate.old_text,
        "new_text": new_text,
        "limit": candidate.limit,
        "platforms": candidate.platforms,
        "expected_payloads": {target_id: row[2] for target_id, row in candidate.targets.items()},
        "payloads": build_target_payloads(candidate, new_text),
    }
    assert db.apply_queue_text_migration(
        QUEUE_900_MIGRATION_KEY,
        [update],
        backup_path="C:/backup.zip",
    ) == 1

    after = db.get_batch(batch_id)
    assert after.scheduled_at == before_schedule
    assert after.status == before_status
    assert [target.id for target in after.targets] == before_target_ids
    assert [target.status for target in after.targets] == before_target_statuses
    assert db.get_group(group_id).media_file_id == before_media
    assert db.get_group(group_id).rewrite_text == new_text
    assert db.queue_text_migration_completed(QUEUE_900_MIGRATION_KEY)
    with pytest.raises(ValueError):
        db.apply_queue_text_migration(
            QUEUE_900_MIGRATION_KEY,
            [update],
            backup_path="C:/backup2.zip",
        )


def test_fix28_scan_blocks_active_or_overdue_package(tmp_path: Path) -> None:
    db, _group_id, batch_id = _future_db(tmp_path, text=("Факт. " * 220).strip())
    with db.connect() as connection:
        connection.execute(
            "UPDATE publication_batches SET scheduled_at=?,status='pending' WHERE id=?",
            ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(), batch_id),
        )
    scan = scan_queue_for_900_migration(db)
    assert scan.blockers and ("прострочений" in scan.blockers[0] or "сьогодні" in scan.blockers[0])
    assert not scan.candidates


def test_fix28_ollama_compression_uses_fallback_and_hard_limit() -> None:
    class Client:
        def __init__(self, answer: str | Exception):
            self.answer = answer
            self.prompt = ""

        def generate_text(self, _model: str, prompt: str, **_kwargs: object) -> str:
            self.prompt = prompt
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

    primary = Client(OllamaError("primary failed"))
    fallback = Client("Стислий текст із фактами.")
    text, model, used = compress_approved_text(
        "Довгий схвалений текст.",
        100,
        primary_client=primary,  # type: ignore[arg-type]
        primary_model="main",
        fallback_client=fallback,  # type: ignore[arg-type]
        fallback_model="backup",
    )
    assert text == "Стислий текст із фактами."
    assert model == "backup" and used
    assert "не більше 100 символів" in fallback.prompt
    prompt = build_queue_compression_prompt("Текст", 321)
    assert "не більше 321 символів" in prompt
    assert "не додавай жодного нового факту" in prompt


def test_fix28_startup_gate_keeps_worker_off_until_migration() -> None:
    source = (Path(__file__).parents[1] / "content_agent" / "ui" / "main_window.py").read_text(encoding="utf-8")
    dialog = (Path(__file__).parents[1] / "content_agent" / "ui" / "queue_migration_dialog.py").read_text(encoding="utf-8")
    assert 'root.title("UA FREE Content Tool — v1.1.2")' in source
    assert "self.root.after(250, self._startup_queue_migration_gate)" in source
    assert "self.worker_thread.start()" in source
    assert source.index("def _startup_queue_migration_gate") < source.index("def close")
    assert "Застосувати готові тексти до черги" in dialog
    assert "create_backup()" in dialog
    assert "apply_queue_text_migration" in dialog
