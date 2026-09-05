from __future__ import annotations

import json
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from tzlocal import get_localzone, get_localzone_name

from .paths import data_dir


SYSTEM_TIMEZONE = "system"
SYSTEM_LABEL_UA = "Системний (автоматично)"
SYSTEM_LABEL_EN = "System (automatic)"
SETTINGS_FILENAME = "timezone_v1_4_rc19.json"


class TimezoneSettingsError(ValueError):
    pass


def settings_path() -> Path:
    return data_dir() / SETTINGS_FILENAME


def normalize_timezone_name(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return SYSTEM_TIMEZONE
    if text.casefold() in {
        "system",
        SYSTEM_LABEL_UA.casefold(),
        SYSTEM_LABEL_EN.casefold(),
    }:
        return SYSTEM_TIMEZONE
    try:
        ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise TimezoneSettingsError(f"Невідомий часовий пояс: {text}") from exc
    return text


def load_timezone_name(path: Path | None = None) -> str:
    target = path or settings_path()
    if not target.exists():
        return SYSTEM_TIMEZONE
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SYSTEM_TIMEZONE
    try:
        return normalize_timezone_name(payload.get("timezone_name", SYSTEM_TIMEZONE))
    except TimezoneSettingsError:
        return SYSTEM_TIMEZONE


def save_timezone_name(value: object, path: Path | None = None) -> str:
    normalized = normalize_timezone_name(value)
    target = path or settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"timezone_name": normalized}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return normalized


def system_timezone_name() -> str:
    try:
        name = str(get_localzone_name() or "").strip()
    except Exception:
        name = ""
    if name:
        return name
    try:
        local = get_localzone()
        key = str(getattr(local, "key", "") or "").strip()
        if key:
            return key
        return str(local)
    except Exception:
        local = datetime.now().astimezone().tzinfo
        return str(local or "local")


def resolve_timezone(value: object) -> tzinfo:
    normalized = normalize_timezone_name(value)
    if normalized == SYSTEM_TIMEZONE:
        try:
            return get_localzone()
        except Exception:
            return datetime.now().astimezone().tzinfo or timezone.utc
    return ZoneInfo(normalized)


def timezone_display_name(value: object, *, language: str = "uk") -> str:
    normalized = normalize_timezone_name(value)
    if normalized == SYSTEM_TIMEZONE:
        prefix = SYSTEM_LABEL_EN if str(language).lower().startswith("en") else SYSTEM_LABEL_UA
        return f"{prefix}: {system_timezone_name()}"
    return normalized


def timezone_choices(*, language: str = "uk") -> list[str]:
    system_label = SYSTEM_LABEL_EN if str(language).lower().startswith("en") else SYSTEM_LABEL_UA
    try:
        zones = sorted(available_timezones())
    except Exception:
        zones = []
    return [system_label, *zones]


def choice_to_timezone_name(value: object) -> str:
    text = str(value or "").strip()
    if text.casefold() in {SYSTEM_LABEL_UA.casefold(), SYSTEM_LABEL_EN.casefold()}:
        return SYSTEM_TIMEZONE
    return normalize_timezone_name(text)


def timezone_name_to_choice(value: object, *, language: str = "uk") -> str:
    normalized = normalize_timezone_name(value)
    if normalized == SYSTEM_TIMEZONE:
        return SYSTEM_LABEL_EN if str(language).lower().startswith("en") else SYSTEM_LABEL_UA
    return normalized


def format_ui_timestamp(value: object, zone: tzinfo, *, seconds: bool = True) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    if text == "—":
        return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return text
    if parsed.tzinfo is None:
        # Internal timestamps are UTC. Old rows without an offset are therefore
        # interpreted as UTC instead of silently borrowing the workstation zone.
        parsed = parsed.replace(tzinfo=timezone.utc)
    pattern = "%d.%m.%Y %H:%M:%S" if seconds else "%d.%m.%Y %H:%M"
    return parsed.astimezone(zone).strftime(pattern)
