from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import content_agent.collector_backfill_v1_4_rc20 as rc20
from content_agent.models import CollectedArticle, Source


def _source(kind: str, url: str = "@example_channel") -> Source:
    return Source(id=1, kind=kind, name="Example", url=url, enabled=True, last_checked_at=None)


def _telegram_page(rows: list[tuple[int, str, str]]) -> str:
    return "\n".join(
        f'''<div class="tgme_widget_message" data-post="example_channel/{message_id}">
        <div class="tgme_widget_message_text">{text}</div>
        <time datetime="{when}"></time>
        </div>'''
        for message_id, when, text in rows
    )


def test_recovery_policy_uses_working_timezone_and_gap_overlap() -> None:
    berlin = ZoneInfo("Europe/Berlin")
    now = datetime(2026, 9, 5, 17, 0, tzinfo=berlin)
    midnight = datetime(2026, 9, 5, 0, 0, tzinfo=berlin)

    assert rc20.recovery_not_before(None, now=now, zone=berlin) == midnight
    assert rc20.recovery_not_before(
        "2026-09-05T14:58:00+00:00", now=now, zone=berlin
    ) is None

    stale_checked = datetime(2026, 9, 5, 13, 0, tzinfo=timezone.utc)
    expected = stale_checked.astimezone(berlin) - rc20.RECOVERY_OVERLAP
    assert rc20.recovery_not_before(
        stale_checked.isoformat(), now=now, zone=berlin
    ) == expected

    assert rc20.recovery_not_before(
        "2026-09-04T22:30:00+00:00", now=now, zone=berlin
    ) == midnight
    assert rc20.recovery_not_before(
        "2026-09-05T14:58:00+00:00",
        now=now,
        zone=berlin,
        force_full_day=True,
    ) == midnight
    assert rc20.recovery_not_before(
        "2026-09-05T14:58:00+00:00",
        now=now,
        zone=berlin,
        manual=True,
    ) == midnight


def test_telegram_recovery_pages_back_to_day_boundary(monkeypatch) -> None:
    kyiv = ZoneInfo("Europe/Kyiv")
    boundary = datetime(2026, 9, 5, 0, 0, tzinfo=kyiv)
    pages = {
        "https://t.me/s/example_channel": _telegram_page(
            [
                (105, "2026-09-05T15:00:00+00:00", "five"),
                (106, "2026-09-05T16:00:00+00:00", "six"),
                (107, "2026-09-05T17:00:00+00:00", "seven"),
            ]
        ),
        "https://t.me/s/example_channel?before=105": _telegram_page(
            [
                (102, "2026-09-05T08:00:00+00:00", "two"),
                (103, "2026-09-05T09:00:00+00:00", "three"),
                (104, "2026-09-05T10:00:00+00:00", "four"),
            ]
        ),
        "https://t.me/s/example_channel?before=102": _telegram_page(
            [
                (99, "2026-09-04T20:30:00+00:00", "old"),
                (100, "2026-09-04T21:30:00+00:00", "midnight-plus"),
                (101, "2026-09-05T01:00:00+00:00", "one"),
            ]
        ),
    }
    calls: list[str] = []

    def fake_fetch(url: str, **_kwargs):
        calls.append(url)
        return SimpleNamespace(body=pages[url].encode("utf-8"))

    monkeypatch.setattr(rc20, "fetch_url", fake_fetch)
    items = rc20.collect_source_rc20(
        _source("telegram"), zone=kyiv, not_before=boundary
    )

    assert calls == [
        "https://t.me/s/example_channel",
        "https://t.me/s/example_channel?before=105",
        "https://t.me/s/example_channel?before=102",
    ]
    assert [item.external_id for item in items] == [
        "example_channel/100",
        "example_channel/101",
        "example_channel/102",
        "example_channel/103",
        "example_channel/104",
        "example_channel/105",
        "example_channel/106",
        "example_channel/107",
    ]


def test_telegram_recovery_stops_when_cursor_does_not_progress(monkeypatch) -> None:
    zone = ZoneInfo("Europe/Kyiv")
    boundary = datetime(2026, 9, 5, 0, 0, tzinfo=zone)
    page = _telegram_page(
        [(50, "2026-09-05T12:00:00+00:00", "same")]
    )
    calls: list[str] = []

    def fake_fetch(url: str, **_kwargs):
        calls.append(url)
        return SimpleNamespace(body=page.encode("utf-8"))

    monkeypatch.setattr(rc20, "fetch_url", fake_fetch)
    items = rc20.collect_source_rc20(
        _source("telegram"), zone=zone, not_before=boundary
    )

    assert len(items) == 1
    assert calls == [
        "https://t.me/s/example_channel",
        "https://t.me/s/example_channel?before=50",
    ]


def test_rss_recovery_is_not_capped_at_thirty(monkeypatch) -> None:
    zone = ZoneInfo("Europe/Kyiv")
    boundary = datetime(2026, 9, 5, 0, 0, tzinfo=zone)
    rows = []
    for index in range(40):
        hour = index % 20
        rows.append(
            f"<item><title>Item {index}</title><link>https://example.com/{index}</link>"
            f"<guid>id-{index}</guid><description>Body {index}</description>"
            f"<pubDate>2026-09-05T{hour:02d}:00:00+00:00</pubDate></item>"
        )
    xml = ("<rss><channel>" + "".join(rows) + "</channel></rss>").encode("utf-8")

    monkeypatch.setattr(
        rc20,
        "fetch_url",
        lambda *_args, **_kwargs: SimpleNamespace(body=xml),
    )
    monkeypatch.setattr(rc20, "_fetch_article_text", lambda _url, fallback: fallback)

    items = rc20.collect_source_rc20(
        _source("rss", "https://example.com/feed.xml"),
        zone=zone,
        not_before=boundary,
    )
    assert len(items) == 40


def test_no_recovery_boundary_keeps_legacy_lightweight_collector(monkeypatch) -> None:
    sentinel = [
        CollectedArticle(
            external_id="x",
            title="x",
            url="https://example.com/x",
            raw_text="x",
            published_at="2026-09-05T10:00:00+00:00",
        )
    ]
    monkeypatch.setattr(rc20, "collect_source", lambda _source: sentinel)
    result = rc20.collect_source_rc20(
        _source("telegram"), zone=ZoneInfo("Europe/Kyiv"), not_before=None
    )
    assert result is sentinel


def test_upgrade_marker_roundtrip(tmp_path: Path) -> None:
    marker = tmp_path / "marker.json"
    assert rc20.rc20_upgrade_backfill_done(marker) is False
    rc20.mark_rc20_upgrade_backfill_done(marker)
    assert rc20.rc20_upgrade_backfill_done(marker) is True
