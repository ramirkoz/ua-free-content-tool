from __future__ import annotations

from pathlib import Path

import pytest

from content_agent.database_v1_4_rc14 import Database
from content_agent.models import CollectedArticle


def _add(db: Database, source_id: int, *, external_id: str, title: str, text: str) -> int:
    inserted = db.insert_collected(
        source_id,
        [
            CollectedArticle(
                external_id=external_id,
                title=title,
                url=f"https://example.test/{external_id}",
                raw_text=text,
                published_at="2026-09-03T12:00:00+03:00",
            )
        ],
        enforce_today=False,
    )
    assert inserted == 1
    groups = db.list_groups(limit=None)
    return next(group.id for group in groups if group.canonical_title == title)


def _database(tmp_path: Path) -> tuple[Database, int]:
    db = Database(tmp_path / "content.sqlite3")
    source_id = db.add_source("url", "Test source", "https://example.test/")
    return db, source_id


def test_keyword_search_requires_all_terms_across_title_and_body(tmp_path: Path) -> None:
    db, source_id = _database(tmp_path)
    first = _add(
        db,
        source_id,
        external_id="one",
        title="КИЇВ запускає експеримент",
        text="Мережа тестує персональну знижку для покупців.",
    )
    _add(
        db,
        source_id,
        external_id="two",
        title="Інша новина про Київ",
        text="Тут немає потрібної комерційної механіки.",
    )
    _add(
        db,
        source_id,
        external_id="three",
        title="Знижка в іншому місті",
        text="Кампанія не пов'язана з потрібною подією.",
    )

    matches = db.search_inbox_groups("київ знижка")
    assert [group.id for group in matches] == [first]
    assert matches[0].articles[0].raw_text.startswith("Мережа тестує")


def test_keyword_search_does_not_offer_approved_blocks_for_merge(tmp_path: Path) -> None:
    db, source_id = _database(tmp_path)
    group_id = _add(
        db,
        source_id,
        external_id="approved",
        title="Ключова новина",
        text="У тексті є слово механіка.",
    )
    db.set_group_status(group_id, "approved")

    assert db.search_inbox_groups("ключова механіка") == []


def test_detach_article_returns_it_to_inbox_without_deleting_data(tmp_path: Path) -> None:
    db, source_id = _database(tmp_path)
    target_id = _add(db, source_id, external_id="lead", title="Основна подія", text="Головний факт.")
    wrong_id = _add(db, source_id, external_id="wrong", title="Помилкова новина", text="Інша подія.")
    third_id = _add(db, source_id, external_id="third", title="Друга правильна новина", text="Той самий сюжет.")

    moved = db.merge_groups(target_id, [target_id, third_id, wrong_id])
    assert moved == 2
    merged = db.get_group(target_id)
    assert merged.source_count == 3
    wrong_article = next(article for article in merged.articles if article.title == "Помилкова новина")

    db.save_group_rewrite(
        target_id,
        headline="Чернетка",
        fact_card="Факти",
        rewrite_text="Старий рерайт, який після зміни складу вже не можна вважати валідним.",
        platform_texts={"telegram": "Старий рерайт"},
    )

    created = db.detach_articles_from_group(target_id, [wrong_article.id])
    assert len(created) == 1

    remaining = db.get_group(target_id)
    restored = db.get_group(created[0])
    assert remaining.source_count == 2
    assert remaining.status == "new"
    assert remaining.rewrite_text == ""
    assert {article.title for article in remaining.articles} == {"Основна подія", "Друга правильна новина"}
    assert restored.source_count == 1
    assert restored.status == "new"
    assert restored.articles[0].id == wrong_article.id
    assert restored.articles[0].title == "Помилкова новина"


def test_detach_reanchors_title_if_removed_article_owned_canonical_title(tmp_path: Path) -> None:
    db, source_id = _database(tmp_path)
    target_id = _add(db, source_id, external_id="lead", title="Хибний заголовок", text="Не та подія.")
    good_id = _add(db, source_id, external_id="good", title="Правильна подія", text="Потрібний матеріал.")
    db.merge_groups(target_id, [target_id, good_id])
    group = db.get_group(target_id)
    lead = next(article for article in group.articles if article.title == "Хибний заголовок")

    db.detach_articles_from_group(target_id, [lead.id])

    remaining = db.get_group(target_id)
    assert remaining.canonical_title == "Правильна подія"
    assert remaining.source_count == 1


def test_detach_refuses_to_empty_the_original_block(tmp_path: Path) -> None:
    db, source_id = _database(tmp_path)
    target_id = _add(db, source_id, external_id="one", title="Перша", text="Один.")
    second_id = _add(db, source_id, external_id="two", title="Друга", text="Два.")
    db.merge_groups(target_id, [target_id, second_id])
    group = db.get_group(target_id)

    with pytest.raises(ValueError, match="залишитися хоча б одна"):
        db.detach_articles_from_group(target_id, [article.id for article in group.articles])
