from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from content_agent.database_v1_4_rc18 import Database
from content_agent.models import CollectedArticle
from content_agent.scheduling import KYIV
from content_agent.ui.v1_4_rc18_window import milliseconds_until_next_kyiv_rollover


def _item(external_id: str, title: str, published_at: str) -> CollectedArticle:
    return CollectedArticle(
        external_id,
        title,
        f"https://example.com/{external_id}",
        f"Текст матеріалу {external_id}",
        published_at,
    )


def _latest_group_id(db: Database) -> int:
    with db.connect() as con:
        row = con.execute("SELECT id FROM news_groups ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    return int(row[0])


def test_rc18_midnight_rollover_archives_previous_day_blocks(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite3")
    source = db.add_source("rss", "Test", "https://example.com/feed")
    now = datetime(2026, 9, 5, 0, 0, 2, tzinfo=KYIV)
    old = datetime(2026, 9, 4, 23, 50, tzinfo=KYIV).isoformat()

    assert db.insert_collected(source, [_item("old", "Новина 4 вересня", old)], enforce_today=False) == 1
    group_id = _latest_group_id(db)

    result = db.rollover_inbox_day(now=now)

    assert result == {
        "archived_groups": 1,
        "trimmed_groups": 0,
        "archived_articles": 1,
    }
    assert db.get_group(group_id).status == "archived"
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1


def test_rc18_mixed_block_keeps_only_current_day_story_in_working_group(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite3")
    first = db.add_source("rss", "Old source", "https://example.com/old-feed")
    second = db.add_source("telegram", "Fresh source", "@fresh")
    now = datetime(2026, 9, 5, 12, 0, tzinfo=KYIV)
    old = datetime(2026, 9, 4, 22, 30, tzinfo=KYIV).isoformat()
    fresh = datetime(2026, 9, 5, 8, 15, tzinfo=KYIV).isoformat()

    assert db.insert_collected(first, [_item("old", "Стара версія події", old)], enforce_today=False) == 1
    old_group = _latest_group_id(db)
    assert db.insert_collected(second, [_item("fresh", "Свіже оновлення події", fresh)], enforce_today=False) == 1
    fresh_group = _latest_group_id(db)
    assert fresh_group != old_group
    assert db.merge_groups(old_group, [old_group, fresh_group]) == 1

    with db.connect() as con:
        con.execute(
            """
            UPDATE news_groups
            SET status='draft',headline='Старий заголовок',fact_card='Старі факти',
                rewrite_text='Старий рерайт',ai_draft_text='Старий AI',platform_texts_json='{"telegram":"old"}'
            WHERE id=?
            """,
            (old_group,),
        )
        con.execute(
            "UPDATE articles SET status='draft',rewrite_text='Старий рерайт' WHERE group_id=?",
            (old_group,),
        )

    result = db.rollover_inbox_day(now=now)

    assert result == {
        "archived_groups": 0,
        "trimmed_groups": 1,
        "archived_articles": 1,
    }
    current = db.get_group(old_group)
    assert current.status == "new"
    assert current.source_count == 1
    assert current.canonical_title == "Свіже оновлення події"
    assert current.headline == ""
    assert current.fact_card == ""
    assert current.rewrite_text == ""
    assert current.articles[0].title == "Свіже оновлення події"
    assert current.articles[0].status == "new"

    archived = db.list_groups(status="archived")
    assert len(archived) == 1
    old_archive = db.get_group(archived[0].id)
    assert old_archive.source_count == 1
    assert old_archive.articles[0].title == "Стара версія події"
    assert old_archive.articles[0].status == "archived"

    # RC18 moves history out of the working group; it does not delete it.
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 2


def test_rc18_approved_yesterday_story_is_hidden_from_inbox_but_preserved(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite3")
    source = db.add_source("rss", "Approved", "https://example.com/approved")
    yesterday = (datetime.now(KYIV) - timedelta(days=1)).replace(hour=23, minute=30).isoformat()
    assert db.insert_collected(
        source,
        [_item("approved-old", "Учорашня схвалена новина", yesterday)],
        enforce_today=False,
    ) == 1
    group_id = _latest_group_id(db)
    db.set_group_status(group_id, "approved")

    assert all(group.id != group_id for group in db.list_groups())
    assert all(group.id != group_id for group in db.list_groups(status="approved"))
    assert db.get_group(group_id).status == "approved"
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM articles WHERE group_id=?", (group_id,)).fetchone()[0] == 1


def test_rc18_rollover_timer_targets_just_after_next_kyiv_midnight() -> None:
    now = datetime(2026, 9, 5, 23, 59, 59, tzinfo=KYIV)
    assert milliseconds_until_next_kyiv_rollover(now=now) == 3000


def test_rc18_rollover_timer_is_dst_safe() -> None:
    # Europe/Kyiv falls back on the last Sunday of October. The helper must aim
    # at local midnight rather than assuming every civil day has exactly 24 hours.
    now = datetime(2026, 10, 25, 0, 30, tzinfo=KYIV)
    delay = milliseconds_until_next_kyiv_rollover(now=now)
    assert 24 * 60 * 60 * 1000 < delay < 25 * 60 * 60 * 1000
