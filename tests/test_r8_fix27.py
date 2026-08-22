from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from content_agent.database import DATABASE_SCHEMA_VERSION, Database
from content_agent.editorial_memory import (
    rank_editorial_examples,
    rank_topic_candidates,
    split_threads_chain,
)
from content_agent.models import CollectedArticle
from content_agent.publication_text import (
    EDITORIAL_TEXT_LIMIT,
    TELEGRAM_MEDIA_CAPTION_LIMIT,
    TextLimitError,
    compose_publication_text,
    validate_editorial_text,
    validate_media_message,
)
from content_agent.publishers import PublishContext, ThreadsPublisher
from content_agent.rewriter import rewrite_article
from content_agent.topic_search import build_topic_prompt

UTC = timezone.utc


def _downgrade_to_fix26_schema(path: Path) -> None:
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("DROP TABLE editorial_examples")
        db.execute("DROP TABLE topic_merge_feedback")
        db.execute("DROP TABLE queue_text_migration_items")
        db.execute("DROP TABLE queue_text_migrations")
        db.executescript(
            """
            CREATE TABLE news_groups_fix26 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new'
                    CHECK(status IN ('new','draft','approved','rejected','archived')),
                headline TEXT NOT NULL DEFAULT '',
                fact_card TEXT NOT NULL DEFAULT '',
                rewrite_text TEXT NOT NULL DEFAULT '',
                platform_texts_json TEXT NOT NULL DEFAULT '{}',
                include_source_link INTEGER NOT NULL DEFAULT 0,
                media_drive_url TEXT NOT NULL DEFAULT '',
                media_file_id TEXT NOT NULL DEFAULT '',
                media_name TEXT NOT NULL DEFAULT '',
                media_kind TEXT NOT NULL DEFAULT '' CHECK(media_kind IN ('','image','video')),
                media_mime TEXT NOT NULL DEFAULT '',
                media_size INTEGER NOT NULL DEFAULT 0,
                explosiveness_score INTEGER NOT NULL DEFAULT 0,
                explosiveness_confidence INTEGER NOT NULL DEFAULT 0,
                explosiveness_details_json TEXT NOT NULL DEFAULT '{}',
                recommended_platforms_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO news_groups_fix26(
                id,canonical_title,status,headline,fact_card,rewrite_text,platform_texts_json,
                include_source_link,media_drive_url,media_file_id,media_name,media_kind,media_mime,
                media_size,explosiveness_score,explosiveness_confidence,explosiveness_details_json,
                recommended_platforms_json,created_at,updated_at
            )
            SELECT id,canonical_title,status,headline,fact_card,rewrite_text,platform_texts_json,
                   include_source_link,media_drive_url,media_file_id,media_name,media_kind,media_mime,
                   media_size,explosiveness_score,explosiveness_confidence,explosiveness_details_json,
                   recommended_platforms_json,created_at,updated_at
            FROM news_groups;
            DROP TABLE news_groups;
            ALTER TABLE news_groups_fix26 RENAME TO news_groups;
            """
        )
        db.execute("PRAGMA user_version=4")
        db.commit()
    finally:
        db.close()


def test_fix28_additive_migration_preserves_sources_settings_projection_and_queue(tmp_path: Path) -> None:
    path = tmp_path / "working.sqlite3"
    original = Database(path)
    source_id = original.add_source("rss", "Робоче джерело", "https://example.com/feed")
    original.insert_collected(
        source_id,
        [CollectedArticle("one", "Важлива новина", "https://example.com/one", "Фактаж", None)],
        enforce_today=False,
    )
    group = original.list_groups()[0]
    original.save_group_rewrite(
        group.id,
        headline="Заголовок",
        fact_card="Факти",
        rewrite_text="Робочий текст",
        platform_texts={platform: "Робочий текст" for platform in ("facebook", "threads", "linkedin", "telegram")},
    )
    scheduled = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    batch_id = original.create_batch(original.lead_article_id(group.id), scheduled, {"telegram": "payload"})
    _downgrade_to_fix26_schema(path)

    upgraded = Database(path)
    assert DATABASE_SCHEMA_VERSION == 8
    assert upgraded.list_sources()[0].name == "Робоче джерело"
    assert upgraded.get_group(group.id).rewrite_text == "Робочий текст"
    batch = upgraded.get_batch(batch_id)
    assert batch.status == "pending"
    assert [(target.platform, target.status) for target in batch.targets] == [("telegram", "pending")]
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 8
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"editorial_examples", "topic_merge_feedback", "queue_text_migrations", "queue_text_migration_items"}.issubset(tables)


def test_fix28_one_editorial_text_limit_and_telegram_caption_budget() -> None:
    seed = "Підтверджений факт без службового тексту. "
    core = (seed * ((EDITORIAL_TEXT_LIMIT // len(seed)) + 2))[:EDITORIAL_TEXT_LIMIT]
    validate_editorial_text(core)
    final = compose_publication_text(core, "telegram", include_source_link=False, source_url="")
    assert len(final) <= TELEGRAM_MEDIA_CAPTION_LIMIT
    validate_media_message(final, "telegram", has_media=True)
    with pytest.raises(TextLimitError):
        validate_editorial_text(core + "х")


def test_fix28_threads_publishes_long_text_as_main_post_and_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    create_fields: list[dict[str, object]] = []
    publish_count = 0

    def fake_post(url: str, fields: dict[str, object], **_kwargs) -> dict[str, object]:
        nonlocal publish_count
        if url.endswith("/threads_publish"):
            publish_count += 1
            return {"id": f"post-{publish_count}"}
        create_fields.append(dict(fields))
        return {"id": f"container-{len(create_fields)}"}

    monkeypatch.setattr("content_agent.publishers._post_form", fake_post)
    publisher = ThreadsPublisher("user", "token")
    saved: list[dict[str, object]] = []
    text = ("Перше речення містить важливий факт. " * 14).strip()
    assert 500 < len(text) <= 900
    result = publisher.publish(
        text,
        {},
        PublishContext(before_write=lambda: None, save_progress=lambda value: saved.append(dict(value))),
    )
    assert len(split_threads_chain(text)) == 2
    assert publish_count == 2
    assert create_fields[0].get("reply_to_id") is None
    assert create_fields[1]["reply_to_id"] == "post-1"
    assert result.remote_id == "post-1"
    assert saved[-1]["published_parts"] == 2
    assert saved[-1]["remote_ids"] == ["post-1", "post-2"]


def test_fix28_editorial_memory_uses_approved_manual_result() -> None:
    rows = [
        {
            "id": 1,
            "source_text": "Запоріжжя. Унаслідок атаки пошкоджено будинок, двоє постраждалих.",
            "ai_draft_text": "Чернетка з водою.",
            "final_text": "У Запоріжжі внаслідок атаки пошкоджено будинок, постраждали двоє людей.",
            "headline": "Наслідки атаки",
        },
        {
            "id": 2,
            "source_text": "Футбольний матч завершився перемогою команди.",
            "ai_draft_text": "Спорт.",
            "final_text": "Команда перемогла у матчі.",
            "headline": "Матч",
        },
    ]
    ranked = rank_editorial_examples("Після атаки у Запоріжжі є двоє постраждалих", rows)
    assert ranked and ranked[0].id == 1

    class Client:
        prompt = ""

        def generate_json(self, _model, prompt, _schema):
            self.prompt = prompt
            return {"headline": "У Запоріжжі після атаки постраждали двоє людей", "rewrite": "У Запоріжжі після атаки постраждали двоє людей."}

    client = Client()
    article = type(
        "A",
        (),
        {
            "title": "Атака",
            "url": "https://example.com",
            "raw_text": "У Запоріжжі після атаки постраждали двоє людей.",
        },
    )()
    rewrite_article(client, "model", article, editorial_examples=ranked)  # type: ignore[arg-type]
    assert "РЕДАКЦІЙНА ПАМ'ЯТЬ" in client.prompt
    assert rows[0]["final_text"] in client.prompt
    assert "не перенось факти з прикладів" in client.prompt


def test_fix28_manual_merge_feedback_boosts_topic_search() -> None:
    anchor = "У Запоріжжі дрон влучив у багатоповерхівку, двоє постраждалих"
    candidate = "Рятувальники завершили роботи у пошкодженому будинку, двоє людей у лікарні"
    unrelated = "У Запоріжжі відкрили новий навчальний центр"
    rows = [
        {"group_id": 2, "text": candidate},
        {"group_id": 3, "text": unrelated},
    ]
    feedback = [
        {
            "decision": "merged",
            "anchor_text": "Дрон атакував будинок у Запоріжжі, є постраждалі",
            "candidate_text": "Рятувальники працюють у пошкодженому будинку, постраждалі в лікарні",
        }
    ]
    ranked = rank_topic_candidates(anchor, rows, feedback=feedback)
    assert ranked
    assert ranked[0].group_id == 2
    assert ranked[0].score > next((item.score for item in ranked if item.group_id == 3), 0)
    prompt = build_topic_prompt("Атака", anchor, rows, feedback=feedback)
    assert "ПОПЕРЕДНІ РУЧНІ ОБ'ЄДНАННЯ" in prompt
    assert feedback[0]["candidate_text"] in prompt


def test_fix28_ui_contract_has_one_text_and_topic_search() -> None:
    source = (Path(__file__).parents[1] / "content_agent" / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert 'root.title("UA FREE Content Tool — v1.3.1-rc7")' in source
    assert 'text="Текст публікації: один для всіх мереж"' in source
    assert 'text="Пошук схожих за темою матеріалів"' in source
    assert "def find_all_by_topic(self) -> None:" in source
    assert "Синхронізувати всі тексти" not in source
    assert '("facebook", "Facebook")' not in source
    assert "record_editorial_example" in source
