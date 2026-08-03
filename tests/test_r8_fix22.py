from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from content_agent.database import Database
from content_agent.models import CollectedArticle

UTC = timezone.utc


def _make_group(db: Database, suffix: str, title: str, body: str) -> int:
    source_id = db.add_source("rss", f"FIX23 {suffix}", f"https://example.com/fix22-{suffix}.xml")
    assert db.insert_collected(
        source_id,
        [
            CollectedArticle(
                external_id=f"fix22-{suffix}",
                title=title,
                url=f"https://example.com/fix22-{suffix}",
                raw_text=body,
                published_at=None,
            )
        ],
        enforce_today=False,
    ) == 1
    return next(item.id for item in db.list_groups() if item.canonical_title == title)


def test_fix22_manual_merge_moves_all_sources_and_resets_derived_copy(tmp_path: Path) -> None:
    db = Database(tmp_path / "merge.sqlite3")
    target_id = _make_group(db, "alpha", "Енергетична зустріч у Києві", "Уряд обговорив відновлення мереж.")
    second_id = _make_group(db, "beta", "Навчання медиків у Львові", "Медики провели окремі навчання.")
    third_id = _make_group(db, "gamma", "Новий міст у Черкасах", "У Черкасах завершили будівельні роботи.")

    db.save_group_rewrite(
        target_id,
        headline="Старий заголовок",
        fact_card="Стара факт-картка",
        rewrite_text="Старий рерайт",
        platform_texts={"telegram": "Старий текст"},
    )
    db.set_group_media(
        target_id,
        drive_url="https://drive.google.com/file/d/target/view",
        file_id="target",
        name="target.jpg",
        kind="image",
        mime="image/jpeg",
        size=100,
    )

    moved = db.merge_groups(target_id, [target_id, second_id, third_id])

    assert moved == 2
    merged = db.get_group(target_id)
    assert merged.canonical_title == "Енергетична зустріч у Києві"
    assert merged.source_count == 3
    assert merged.status == "new"
    assert merged.headline == ""
    assert merged.fact_card == ""
    assert merged.rewrite_text == ""
    assert merged.platform_texts == {}
    assert merged.media_file_id == "target"
    assert merged.media_name == "target.jpg"
    assert merged.explosiveness_score > 0
    assert {article.group_id for article in merged.articles} == {target_id}
    with pytest.raises(KeyError):
        db.get_group(second_id)
    with pytest.raises(KeyError):
        db.get_group(third_id)


def test_fix22_merge_refuses_additional_block_media_atomically(tmp_path: Path) -> None:
    db = Database(tmp_path / "media.sqlite3")
    target_id = _make_group(db, "one", "Окрема дипломатична зустріч", "Дипломати провели переговори.")
    source_id = _make_group(db, "two", "Окремий спортивний турнір", "Команда виграла фінальний матч.")
    db.set_group_media(
        source_id,
        drive_url="https://drive.google.com/file/d/source/view",
        file_id="source",
        name="source.mp4",
        kind="video",
        mime="video/mp4",
        size=200,
    )

    with pytest.raises(ValueError, match="прикріплено медіа"):
        db.merge_groups(target_id, [target_id, source_id])

    assert db.get_group(target_id).source_count == 1
    assert db.get_group(source_id).source_count == 1


def test_fix22_merge_refuses_any_queue_history_atomically(tmp_path: Path) -> None:
    db = Database(tmp_path / "queue.sqlite3")
    target_id = _make_group(db, "queue-one", "Окрема новина про освіту", "Школа відкрила новий клас.")
    source_id = _make_group(db, "queue-two", "Окрема новина про транспорт", "Місто запустило новий маршрут.")
    article_id = db.lead_article_id(source_id)
    db.create_batch(
        article_id,
        (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        {"telegram": "Тестовий текст"},
    )

    with pytest.raises(ValueError, match="історією публікації або чергою"):
        db.merge_groups(target_id, [target_id, source_id])

    assert db.get_group(target_id).source_count == 1
    assert db.get_group(source_id).source_count == 1


def test_fix22_inbox_ui_supports_standard_multiselect_and_manual_merge() -> None:
    source = Path(__file__).parents[1] / "content_agent" / "ui" / "main_window.py"
    text = source.read_text(encoding="utf-8")

    assert 'self.groups_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="extended")' in text
    assert 'text="Об’єднати в один блок"' in text
    assert 'self.groups_tree.bind("<Control-a>", self._select_all_group_rows)' in text
    assert "Shift — діапазон" in text
    assert "def _selected_group_ids(self) -> list[int]:" in text
    assert "def merge_selected_groups(self) -> None:" in text
    assert "self.db.merge_groups(target_group_id, group_ids)" in text
