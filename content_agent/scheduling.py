from __future__ import annotations

from datetime import date, datetime, time, timedelta
from importlib.resources import files
from zoneinfo import ZoneInfo


def _load_kyiv_zone() -> ZoneInfo:
    resource = files("content_agent").joinpath("data", "Europe_Kyiv.tzif")
    try:
        with resource.open("rb") as handle:
            return ZoneInfo.from_file(handle, key="Europe/Kyiv")
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise RuntimeError(
            "Bundled Europe/Kyiv time-zone data is missing or corrupted."
        ) from exc


KYIV = _load_kyiv_zone()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _hour_boundary(day: date, hour: int) -> datetime:
    """Return a Kyiv wall-clock boundary, treating 24:00 as next-day midnight."""

    if hour == 24:
        return datetime.combine(day + timedelta(days=1), time(0, 0), KYIV)
    return datetime.combine(day, time(hour, 0), KYIV)


def _ceil_from_anchor(value: datetime, anchor: datetime, interval_minutes: int) -> datetime:
    """Return the first interval point anchored at ``anchor`` that is >= ``value``."""

    if value <= anchor:
        return anchor
    step_seconds = int(interval_minutes) * 60
    elapsed_seconds = (value - anchor).total_seconds()
    steps = int(elapsed_seconds // step_seconds)
    candidate = anchor + timedelta(seconds=steps * step_seconds)
    if candidate < value:
        candidate += timedelta(seconds=step_seconds)
    return candidate


def _next_grid_slot_from_now(
    current: datetime,
    *,
    start_hour: int,
    end_hour: int,
    interval_minutes: int,
) -> datetime:
    """Place a first/new cadence slot on a grid anchored at the daily start time."""

    day_start = _hour_boundary(current.date(), start_hour)
    day_end = _hour_boundary(current.date(), end_hour)
    if current < day_start:
        return day_start
    if current >= day_end:
        return _hour_boundary(current.date() + timedelta(days=1), start_hour)

    candidate = _ceil_from_anchor(current, day_start, interval_minutes)
    if candidate >= day_end:
        return _hour_boundary(current.date() + timedelta(days=1), start_hour)
    return candidate


def next_publish_slot(
    *,
    now: datetime | None = None,
    latest_scheduled: datetime | None = None,
    start_hour: int = 9,
    end_hour: int = 20,
    interval_minutes: int = 15,
) -> datetime:
    if interval_minutes < 15:
        raise ValueError("Publication interval cannot be shorter than 15 minutes.")
    if not (0 <= int(start_hour) <= 23):
        raise ValueError("Publication start hour must be between 0 and 23.")
    if not (1 <= int(end_hour) <= 24):
        raise ValueError("Publication end hour must be between 1 and 24.")
    if int(start_hour) >= int(end_hour):
        raise ValueError("Publication start hour must be earlier than end hour.")

    current = (now or datetime.now(KYIV)).astimezone(KYIV).replace(microsecond=0)
    interval = int(interval_minutes)

    if latest_scheduled is None:
        return _next_grid_slot_from_now(
            current,
            start_hour=start_hour,
            end_hour=end_hour,
            interval_minutes=interval,
        )

    latest = latest_scheduled.astimezone(KYIV).replace(second=0, microsecond=0)
    candidate = latest + timedelta(minutes=interval)

    # Keep the cadence anchored to the previous slot. This is the important
    # distinction for intervals such as 45 minutes: 17:45 -> 18:30 -> 19:15.
    # The old implementation added the interval and then rounded the minute of
    # the hour again, turning a configured 45-minute gap into 60 or even 75.
    if candidate < current:
        current_day_start = _hour_boundary(current.date(), start_hour)
        current_day_end = _hour_boundary(current.date(), end_hour)
        if latest.date() == current.date() and current_day_start <= latest < current_day_end:
            candidate = _ceil_from_anchor(current, latest, interval)
        else:
            return _next_grid_slot_from_now(
                current,
                start_hour=start_hour,
                end_hour=end_hour,
                interval_minutes=interval,
            )

    day_start = _hour_boundary(candidate.date(), start_hour)
    day_end = _hour_boundary(candidate.date(), end_hour)
    if candidate < day_start:
        return day_start
    if candidate >= day_end:
        return _hour_boundary(candidate.date() + timedelta(days=1), start_hour)
    return candidate
