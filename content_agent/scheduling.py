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

    current = (now or datetime.now(KYIV)).astimezone(KYIV)
    candidate = current
    if latest_scheduled is not None:
        latest = latest_scheduled.astimezone(KYIV)
        candidate = max(candidate, latest + timedelta(minutes=interval_minutes))

    day_start = _hour_boundary(candidate.date(), start_hour)
    day_end = _hour_boundary(candidate.date(), end_hour)
    if candidate < day_start:
        candidate = day_start
    elif candidate >= day_end:
        candidate = _hour_boundary(candidate.date() + timedelta(days=1), start_hour)

    minute = candidate.minute
    remainder = minute % interval_minutes
    if remainder or candidate.second or candidate.microsecond:
        candidate = candidate.replace(second=0, microsecond=0) + timedelta(
            minutes=(interval_minutes - remainder) if remainder else interval_minutes
        )

    day_end = _hour_boundary(candidate.date(), end_hour)
    if candidate >= day_end:
        candidate = _hour_boundary(candidate.date() + timedelta(days=1), start_hour)
    return candidate
