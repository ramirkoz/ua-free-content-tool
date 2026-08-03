from __future__ import annotations

from datetime import datetime, time, timedelta
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
    return datetime.fromisoformat(value)


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
    current = (now or datetime.now(KYIV)).astimezone(KYIV)
    candidate = current
    if latest_scheduled is not None:
        latest = latest_scheduled.astimezone(KYIV)
        candidate = max(candidate, latest + timedelta(minutes=interval_minutes))

    day_start = datetime.combine(candidate.date(), time(start_hour, 0), KYIV)
    day_end = datetime.combine(candidate.date(), time(end_hour, 0), KYIV)
    if candidate < day_start:
        candidate = day_start
    elif candidate >= day_end:
        candidate = datetime.combine(candidate.date() + timedelta(days=1), time(start_hour, 0), KYIV)

    minute = candidate.minute
    remainder = minute % interval_minutes
    if remainder or candidate.second or candidate.microsecond:
        candidate = candidate.replace(second=0, microsecond=0) + timedelta(
            minutes=(interval_minutes - remainder) if remainder else interval_minutes
        )
    day_end = datetime.combine(candidate.date(), time(end_hour, 0), KYIV)
    if candidate >= day_end:
        candidate = datetime.combine(candidate.date() + timedelta(days=1), time(start_hour, 0), KYIV)
    return candidate
