from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import content_agent.collector_daily_coverage_v1_4_rc21 as rc21
from content_agent.database import _iso
from content_agent.database_v1_4_rc21 import Database
from content_agent.models import Source


def _telegram_source() -> Source:
    return Source(id=1, kind="telegram", name="Example", url="@example_channel", enabled=True, last_checked_at=None)


def _telegram_page(rows: list[tuple[int, str, str]]) -> str:
    return "\n".join(
        f'''<div class="tgme_widget_message" data-post="example_channel/{message_id}">
        <div class="tgme_widget_message_text">{text}</div>
        <time datetime="{when}"></time>
        </div>'''
        for message_id, when, text in rows
    )


def test_telegram_daily_coverage_requires_real_midnight_crossing(monkeypatch) -> None:
    zone = ZoneInfo("Europe/Kyiv")
    boundary = datetime(2026, 9, 6, 0, 0, tzinfo=zone)
    pages = {
        "https://t.me/s/example_channel": _telegram_page(
            [(102, "2026-09-06T10:00:00+00:00", "newer"), (103, "2026-09-06T11:00:00+00:00", "latest")]
        ),
        "https://t.me/s/example_channel?before=102": _telegram_page(
            [(100, "2026-09-06T07:00:00+00:00", "older"), (101, "2026-09-06T08:00:00+00:00", "middle")]
        ),
        # Pagination stalls here while all visible messages are still after Kyiv midnight.
        "https://t.me/s/example_channel?before=100": _telegram_page(
            [(100, "2026-09-06T07:00:00+00:00", "same cursor")]
        ),
    }

    monkeypatch.setattr(
        rc21,
        "fetch_url",
        lambda url, **_kwargs: SimpleNamespace(body=pages[url].encode("utf-8")),
    )
    result = rc21.collect_source_rc21(
        _telegram_source(), zone=zone, not_before=boundary, require_full_day=True
    )

    assert result.complete is False
    assert len(result.items) == 4
    assert "cursor" in result.detail


def test_telegram_daily_coverage_completes_only_after_older_post_seen(monkeypatch) -> None:
    zone = ZoneInfo("Europe/Kyiv")
    boundary = datetime(2026, 9, 6, 0, 0, tzinfo=zone)
    pages = {
        "https://t.me/s/example_channel": _telegram_page(
            [(103, "2026-09-06T10:00:00+00:00", "latest"), (104, "2026-09-06T11:00:00+00:00", "newest")]
        ),
        "https://t.me/s/example_channel?before=103": _telegram_page(
            [
                (100, "2026-09-05T20:30:00+00:00", "before Kyiv midnight"),
                (101, "2026-09-05T22:30:00+00:00", "after Kyiv midnight"),
                (102, "2026-09-06T01:00:00+00:00", "morning"),
            ]
        ),
    }
    calls: list[str] = []

    def fake_fetch(url: str, **_kwargs):
        calls.append(url)
        return SimpleNamespace(body=pages[url].encode("utf-8"))

    monkeypatch.setattr(rc21, "fetch_url", fake_fetch)
    result = rc21.collect_source_rc21(
        _telegram_source(), zone=zone, not_before=boundary, require_full_day=True
    )

    assert result.complete is True
    assert calls == ["https://t.me/s/example_channel", "https://t.me/s/example_channel?before=103"]
    assert [item.external_id for item in result.items] == [
        "example_channel/101",
        "example_channel/102",
        "example_channel/103",
        "example_channel/104",
    ]


def test_coverage_state_is_scoped_to_one_working_date(tmp_path: Path) -> None:
    path = tmp_path / "coverage.json"
    state = rc21.empty_coverage_state("2026-09-06")
    result = rc21.CoverageResult(items=[], complete=True, detail="ok")
    rc21.update_source_coverage(
        state,
        source=_telegram_source(),
        result=result,
        checked_at=datetime.fromisoformat("2026-09-06T12:00:00+03:00"),
    )
    rc21.save_coverage_state(state, path)

    assert rc21.source_coverage_complete(
        rc21.load_coverage_state(working_date="2026-09-06", path=path), 1
    ) is True
    assert rc21.source_coverage_complete(
        rc21.load_coverage_state(working_date="2026-09-07", path=path), 1
    ) is False


def _seed_groups(db: Database, count: int) -> None:
    source_id = db.add_source("rss", "Source", "https://example.com/feed")
    now = _iso()
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            for index in range(count):
                cursor = con.execute(
                    "INSERT INTO news_groups(canonical_title,status,created_at,updated_at) VALUES(?,?,?,?)",
                    (f"Story {index}", "new", now, now),
                )
                group_id = int(cursor.lastrowid)
                con.execute(
                    """
                    INSERT INTO articles(
                        source_id,group_id,external_id,content_hash,title,url,raw_text,
                        published_at,discovered_at,status,headline,fact_card,rewrite_text,platform_texts_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,'new','','','','{}')
                    """,
                    (
                        source_id,
                        group_id,
                        f"ext-{index}",
                        f"hash-{index}",
                        f"Story {index}",
                        f"https://example.com/{index}",
                        f"Body {index}",
                        now,
                        now,
                    ),
                )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise


def test_rc21_working_inbox_is_not_capped_at_200(tmp_path: Path) -> None:
    db = Database(tmp_path / "rc21.sqlite3")
    _seed_groups(db, 350)
    assert len(db.list_groups()) == 350
    assert len(db.list_groups(limit=200)) == 200


def test_rc21_counts_raw_news_for_today(tmp_path: Path) -> None:
    db = Database(tmp_path / "rc21-count.sqlite3")
    _seed_groups(db, 7)
    assert db.count_today_articles() == 7
