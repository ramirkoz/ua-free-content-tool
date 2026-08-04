from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from content_agent.database import DATABASE_SCHEMA_VERSION, Database
from content_agent.editorial_memory import matches_content_exclusion
from content_agent.models import Article, CollectedArticle, NewsGroup
from content_agent.rewriter import _clean_source_text, _source_payload, rewrite_article

UTC = timezone.utc


def _article(article_id: int, title: str, text: str, source: str = "Джерело") -> Article:
    return Article(
        id=article_id,
        source_id=article_id,
        title=title,
        url=f"https://example.com/{article_id}",
        raw_text=text,
        status="new",
        source_name=source,
        published_at="2026-07-31T12:00:00+03:00",
    )


def test_fix29_simple_delete_does_not_create_exclusion(tmp_path: Path) -> None:
    db = Database(tmp_path / "simple.sqlite3")
    source_id = db.add_source("rss", "Джерело", "https://example.com/feed")
    assert db.insert_collected(
        source_id,
        [CollectedArticle("one", "Технологічна новина", "https://example.com/one", "Компанія показала новий пристрій.", None)],
        enforce_today=False,
    ) == 1
    group_id = db.list_groups()[0].id
    db.set_groups_status([group_id], "rejected")
    assert db.content_exclusion_count() == 0
    assert db.get_group(group_id).status == "rejected"


def test_fix29_remembered_exclusion_filters_similar_future_news_and_can_be_undone(tmp_path: Path) -> None:
    db = Database(tmp_path / "exclude.sqlite3")
    first_source = db.add_source("rss", "Перше", "https://example.com/first")
    second_source = db.add_source("rss", "Друге", "https://example.com/second")
    title = "У Києві відкрили виставку декоративних роботів"
    text = "У Києві відкрили виставку декоративних роботів для міського фестивалю. Організатори показали десять інсталяцій."
    assert db.insert_collected(
        first_source,
        [CollectedArticle("one", title, "https://example.com/one", text, None)],
        enforce_today=False,
    ) == 1
    group_id = db.list_groups()[0].id
    assert db.remember_content_exclusions([group_id]) == 1
    assert db.content_exclusion_count() == 1

    similar = "На міському фестивалі у Києві показали десять декоративних роботів та нові інсталяції."
    assert db.insert_collected(
        second_source,
        [CollectedArticle("two", "Декоративні роботи на фестивалі у Києві", "https://example.com/two", similar, None)],
        enforce_today=False,
    ) == 0

    assert db.forget_content_exclusion_for_group(group_id) == 1
    assert db.content_exclusion_count() == 0
    assert db.insert_collected(
        second_source,
        [CollectedArticle("three", "Декоративні роботи на фестивалі у Києві", "https://example.com/three", similar, None)],
        enforce_today=False,
    ) == 1


def test_fix29_exclusion_match_is_conservative_for_generic_overlap() -> None:
    excluded = "В Україні представили екологічну ініціативу з відстеження лелек і GPS-трекерами."
    unrelated = "В Україні уряд представив нову програму підтримки малого бізнесу."
    related = "Екологічна ініціатива в Україні дозволить відстежувати лелек за допомогою GPS-трекерів."
    assert not matches_content_exclusion(unrelated, excluded)
    assert matches_content_exclusion(related, excluded)


def test_fix29_all_sources_are_present_in_one_bounded_dossier() -> None:
    articles = [
        _article(index, f"Заголовок {index}", (f"Факт джерела {index}. " * 180), f"Джерело {index}")
        for index in range(1, 11)
    ]
    group = NewsGroup(
        id=1,
        canonical_title="Збірна тема",
        status="draft",
        created_at="2026-07-31T09:00:00+03:00",
        updated_at="2026-07-31T09:00:00+03:00",
        source_count=10,
        articles=articles,
    )
    _title, _url, payload, _include = _source_payload(group)
    assert len(payload) <= 6000
    assert all(f"ДЖЕРЕЛО {index} ІЗ 10" in payload or f"[{index}/10]" in payload for index in range(1, 11))


class _CaptureClient:
    def __init__(self, responses: list[dict[str, str]]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate_json(self, _model: str, prompt: str, _schema: dict[str, object], **_kwargs: object) -> dict[str, str]:
        self.prompts.append(prompt)
        return self.responses.pop(0)


def test_fix29_rewrite_uses_all_sources_and_reports_count() -> None:
    group = NewsGroup(
        id=1,
        canonical_title="Подія",
        status="draft",
        created_at="2026-07-31T09:00:00+03:00",
        updated_at="2026-07-31T09:00:00+03:00",
        source_count=5,
        articles=[_article(i, f"Заголовок {i}", f"Український факт номер {i}.") for i in range(1, 6)],
    )
    client = _CaptureClient([
        {
            "headline": "Збірний заголовок",
            "fact_card": "Ключові факти зіставлено.",
            "rewrite": "Усі п’ять джерел містять уточнення про одну подію. Дані зіставлено без повторів.",
        }
    ])
    result = rewrite_article(client, "qwen3:4b", group)  # type: ignore[arg-type]
    assert result.source_count_used == 5
    assert result.source_count_total == 5
    assert "Передано моделі джерел: 5 із 5" in result.fact_card
    assert "ДЖЕРЕЛО 5 ІЗ 5" in client.prompts[0]


def test_fix29_overlong_model_output_is_compacted_instead_of_failing() -> None:
    long_text = " ".join(
        [
            "У Києві стартував проєкт із GPS-відстеження десяти білих лелек.",
            "Із другої половини серпня за міграцією птахів можна буде стежити на інтерактивній карті.",
            "Зібрані дані допоможуть науковцям досліджувати маршрути, а енергетикам враховувати їх під час розвитку електромереж.",
        ]
        * 8
    )
    client = _CaptureClient([
        {"headline": "Лелек відстежуватимуть через GPS", "fact_card": "", "rewrite": long_text},
        {"headline": "Лелек відстежуватимуть через GPS", "fact_card": "", "rewrite": long_text},
    ])
    result = rewrite_article(
        client,
        "qwen3:4b",
        _article(
            1,
            "Проєкт відстеження лелек",
            "У Києві стартував проєкт із GPS-відстеження десяти білих лелек. "
            "Із другої половини серпня за міграцією птахів можна буде стежити на інтерактивній карті. "
            "Дані допоможуть науковцям досліджувати маршрути, а енергетикам враховувати їх під час розвитку електромереж.",
        ),
    )  # type: ignore[arg-type]
    assert result.auto_compacted is True
    assert 1 <= len(result.rewrite) <= 900
    assert "десяти білих лелек" in result.rewrite
    assert len(client.prompts) == 2


def test_fix29_source_cleanup_removes_channel_promo() -> None:
    source = (
        "В Україні запустили екологічну ініціативу.\n"
        "Собрані дані допоможуть ученим.\n"
        "INSIDER UA | Прислать контент"
    )
    cleaned = _clean_source_text(source)
    assert "INSIDER UA" not in cleaned
    assert "Прислать контент" not in cleaned
    assert "екологічну ініціативу" in cleaned


def test_fix29_schema_7_adds_exclusions_without_changing_pending_queue(tmp_path: Path) -> None:
    path = tmp_path / "migration.sqlite3"
    db = Database(path)
    source_id = db.add_source("rss", "Джерело", "https://example.com/feed")
    db.insert_collected(
        source_id,
        [CollectedArticle("one", "Новина", "https://example.com/one", "Факти новини.", None)],
        enforce_today=False,
    )
    group = db.list_groups()[0]
    db.save_group_rewrite(
        group.id,
        headline="Заголовок",
        fact_card="Факти",
        rewrite_text="Готовий текст",
        platform_texts={"telegram": "Готовий текст"},
    )
    scheduled = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    batch_id = db.create_batch(db.lead_article_id(group.id), scheduled, {"telegram": "Готовий текст"})

    raw = sqlite3.connect(path)
    try:
        raw.execute("DROP TABLE content_exclusions")
        raw.execute("PRAGMA user_version=6")
        raw.commit()
    finally:
        raw.close()

    upgraded = Database(path)
    assert DATABASE_SCHEMA_VERSION == 8
    batch = upgraded.get_batch(batch_id)
    assert batch.status == "pending"
    assert batch.scheduled_at == db.get_batch(batch_id).scheduled_at
    assert [(target.platform, target.status) for target in batch.targets] == [("telegram", "pending")]
    assert upgraded.content_exclusion_count() == 0
    with sqlite3.connect(path) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 8
        assert raw.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_fix29_schema_upgrade_keeps_completed_900_migration_marker(tmp_path: Path) -> None:
    from content_agent.queue_migration import QUEUE_900_MIGRATION_KEY

    path = tmp_path / "marker.sqlite3"
    db = Database(path)
    db.record_empty_queue_text_migration(QUEUE_900_MIGRATION_KEY)
    assert db.queue_text_migration_completed(QUEUE_900_MIGRATION_KEY)
    raw = sqlite3.connect(path)
    try:
        raw.execute("DROP TABLE content_exclusions")
        raw.execute("PRAGMA user_version=6")
        raw.commit()
    finally:
        raw.close()
    upgraded = Database(path)
    assert upgraded.queue_text_migration_completed(QUEUE_900_MIGRATION_KEY)
