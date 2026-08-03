from __future__ import annotations

from datetime import datetime, timedelta

from content_agent.scheduling import KYIV, next_publish_slot


def test_before_window_moves_to_nine() -> None:
    now = datetime(2026, 7, 24, 7, 12, tzinfo=KYIV)
    result = next_publish_slot(now=now)
    assert (result.hour, result.minute) == (9, 0)


def test_after_window_moves_to_next_day() -> None:
    now = datetime(2026, 7, 24, 20, 1, tzinfo=KYIV)
    result = next_publish_slot(now=now)
    assert result.date().isoformat() == "2026-07-25"
    assert (result.hour, result.minute) == (9, 0)


def test_interval_after_latest() -> None:
    now = datetime(2026, 7, 24, 10, 1, tzinfo=KYIV)
    latest = datetime(2026, 7, 24, 10, 15, tzinfo=KYIV)
    result = next_publish_slot(now=now, latest_scheduled=latest, interval_minutes=15)
    assert (result.hour, result.minute) == (10, 30)


def test_scheduler_rejects_interval_below_15_minutes() -> None:
    import pytest

    with pytest.raises(ValueError):
        next_publish_slot(interval_minutes=14)


def test_bundled_kyiv_timezone_has_expected_offsets() -> None:
    winter = datetime(2026, 1, 15, 12, 0, tzinfo=KYIV)
    summer = datetime(2026, 7, 15, 12, 0, tzinfo=KYIV)
    assert KYIV.key == "Europe/Kyiv"
    assert winter.utcoffset() == timedelta(hours=2)
    assert summer.utcoffset() == timedelta(hours=3)
