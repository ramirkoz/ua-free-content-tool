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


def test_45_minute_interval_is_exact_after_1745() -> None:
    now = datetime(2026, 9, 3, 16, 58, tzinfo=KYIV)
    latest = datetime(2026, 9, 3, 17, 45, tzinfo=KYIV)
    result = next_publish_slot(
        now=now,
        latest_scheduled=latest,
        start_hour=9,
        end_hour=21,
        interval_minutes=45,
    )
    assert (result.hour, result.minute) == (18, 30)


def test_45_minute_interval_is_exact_after_1730() -> None:
    now = datetime(2026, 9, 3, 16, 58, tzinfo=KYIV)
    latest = datetime(2026, 9, 3, 17, 30, tzinfo=KYIV)
    result = next_publish_slot(
        now=now,
        latest_scheduled=latest,
        start_hour=9,
        end_hour=21,
        interval_minutes=45,
    )
    assert (result.hour, result.minute) == (18, 15)


def test_45_minute_sequence_does_not_drift_to_hourly_slots() -> None:
    now = datetime(2026, 9, 3, 16, 58, tzinfo=KYIV)
    first = datetime(2026, 9, 3, 17, 45, tzinfo=KYIV)
    second = next_publish_slot(
        now=now,
        latest_scheduled=first,
        start_hour=9,
        end_hour=21,
        interval_minutes=45,
    )
    third = next_publish_slot(
        now=now,
        latest_scheduled=second,
        start_hour=9,
        end_hour=21,
        interval_minutes=45,
    )
    assert (second.hour, second.minute) == (18, 30)
    assert (third.hour, third.minute) == (19, 15)
    assert second - first == timedelta(minutes=45)
    assert third - second == timedelta(minutes=45)


def test_first_45_minute_slot_is_anchored_to_window_start() -> None:
    now = datetime(2026, 9, 3, 16, 58, tzinfo=KYIV)
    result = next_publish_slot(
        now=now,
        start_hour=9,
        end_hour=21,
        interval_minutes=45,
    )
    assert (result.hour, result.minute) == (17, 15)


def test_missed_45_minute_slot_keeps_same_day_cadence() -> None:
    now = datetime(2026, 9, 3, 18, 40, tzinfo=KYIV)
    latest = datetime(2026, 9, 3, 17, 45, tzinfo=KYIV)
    result = next_publish_slot(
        now=now,
        latest_scheduled=latest,
        start_hour=9,
        end_hour=21,
        interval_minutes=45,
    )
    assert (result.hour, result.minute) == (19, 15)


def test_45_minute_interval_rolls_to_next_window_when_needed() -> None:
    now = datetime(2026, 9, 3, 20, 0, tzinfo=KYIV)
    latest = datetime(2026, 9, 3, 20, 30, tzinfo=KYIV)
    result = next_publish_slot(
        now=now,
        latest_scheduled=latest,
        start_hour=9,
        end_hour=21,
        interval_minutes=45,
    )
    assert result.date().isoformat() == "2026-09-04"
    assert (result.hour, result.minute) == (9, 0)


def test_60_minute_interval_remains_exact() -> None:
    now = datetime(2026, 9, 3, 16, 58, tzinfo=KYIV)
    latest = datetime(2026, 9, 3, 17, 45, tzinfo=KYIV)
    result = next_publish_slot(
        now=now,
        latest_scheduled=latest,
        start_hour=9,
        end_hour=21,
        interval_minutes=60,
    )
    assert (result.hour, result.minute) == (18, 45)


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
