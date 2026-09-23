from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .paths import data_dir
from .scheduling import KYIV


CATALOG_VERSION = 1
SCHEDULE_VERSION = 1
DISPLAY_TITLE_LIMIT = 140


@dataclass(slots=True, frozen=True)
class InstagramDestination:
    id: str
    username: str
    account_type: str = ""
    page_id: str = ""
    page_name: str = ""
    auth_mode: str = "facebook_login"

    @property
    def key(self) -> str:
        return f"instagram:{self.id}"

    @property
    def label(self) -> str:
        name = f"@{self.username}" if self.username else self.id
        return f"{name} (Instagram)"


@dataclass(slots=True, frozen=True)
class TelegramDestination:
    chat_id: str
    title: str
    username: str = ""
    chat_type: str = "channel"
    member_status: str = "administrator"
    can_post_messages: bool = True

    @property
    def key(self) -> str:
        return f"telegram:{self.chat_id}"

    @property
    def label(self) -> str:
        name = self.title or (f"@{self.username}" if self.username else self.chat_id)
        if self.username and f"@{self.username}" not in name:
            name = f"{name} (@{self.username})"
        return f"{name} (Telegram)"


@dataclass(slots=True, frozen=True)
class DestinationSpec:
    key: str
    label: str
    platform: str


@dataclass(slots=True, frozen=True)
class DestinationSchedule:
    start_hour: int
    end_hour: int
    interval_minutes: int

    def validate(self) -> "DestinationSchedule":
        start = int(self.start_hour)
        end = int(self.end_hour)
        interval = int(self.interval_minutes)
        if not 0 <= start <= 23:
            raise ValueError("Початок публікацій має бути між 0 та 23 годиною.")
        if not 1 <= end <= 24 or start >= end:
            raise ValueError("Кінець публікацій має бути пізніше початку і не пізніше 24:00.")
        if not 15 <= interval <= 1440:
            raise ValueError("Інтервал публікацій має бути від 15 до 1440 хвилин.")
        return DestinationSchedule(start, end, interval)


def _atomic_json_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def instagram_catalog_path() -> Path:
    return data_dir() / "instagram_destinations_v1_4.json"


def telegram_catalog_path() -> Path:
    return data_dir() / "telegram_destinations_v2.json"


def save_telegram_catalog(
    rows: Iterable[TelegramDestination],
    *,
    bot_id: str = "",
    bot_username: str = "",
    path: Path | None = None,
) -> Path:
    target = path or telegram_catalog_path()
    normalized: list[TelegramDestination] = []
    seen: set[str] = set()
    for row in rows:
        chat_id = str(row.chat_id or "").strip()
        if not chat_id or chat_id in seen:
            continue
        seen.add(chat_id)
        normalized.append(row)
    _atomic_json_write(
        target,
        {
            "version": 1,
            "updated_at": datetime.now(KYIV).isoformat(timespec="seconds"),
            "bot_id": str(bot_id or "").strip(),
            "bot_username": str(bot_username or "").strip(),
            "channels": [asdict(row) for row in normalized],
        },
    )
    return target


def load_telegram_catalog(path: Path | None = None) -> list[TelegramDestination]:
    target = path or telegram_catalog_path()
    if not target.exists():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or int(payload.get("version") or 0) != 1:
        return []
    rows = payload.get("channels")
    if not isinstance(rows, list):
        return []
    result: list[TelegramDestination] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        chat_id = str(raw.get("chat_id") or "").strip()
        if not chat_id or chat_id in seen:
            continue
        seen.add(chat_id)
        result.append(
            TelegramDestination(
                chat_id=chat_id,
                title=str(raw.get("title") or chat_id).strip(),
                username=str(raw.get("username") or "").strip().lstrip("@"),
                chat_type=str(raw.get("chat_type") or "channel").strip(),
                member_status=str(raw.get("member_status") or "administrator").strip(),
                can_post_messages=bool(raw.get("can_post_messages", True)),
            )
        )
    return result


def telegram_destination_for_key(config, key: str) -> TelegramDestination | None:
    value = str(key or "").strip()
    if not value.startswith("telegram:"):
        return None
    chat_id = value.split(":", 1)[1]
    for row in load_telegram_catalog():
        if row.chat_id == chat_id:
            return row
    legacy = str(getattr(config, "telegram_chat_id", "") or "").strip()
    if chat_id and chat_id == legacy:
        return TelegramDestination(chat_id=chat_id, title=chat_id)
    return None


def destination_schedules_path() -> Path:
    return data_dir() / "destination_schedules_v1_4.json"


def save_instagram_catalog(
    rows: Iterable[InstagramDestination],
    path: Path | None = None,
) -> Path:
    target = path or instagram_catalog_path()
    normalized: list[InstagramDestination] = []
    seen: set[str] = set()
    for row in rows:
        if not row.id or row.id in seen:
            continue
        seen.add(row.id)
        normalized.append(row)
    _atomic_json_write(
        target,
        {
            "version": CATALOG_VERSION,
            "updated_at": datetime.now(KYIV).isoformat(timespec="seconds"),
            # Deliberately no access tokens here. Page tokens remain only in the
            # encrypted application configuration and are resolved at runtime.
            "accounts": [asdict(row) for row in normalized],
        },
    )
    return target


def load_instagram_catalog(path: Path | None = None) -> list[InstagramDestination]:
    target = path or instagram_catalog_path()
    if not target.exists():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or int(payload.get("version") or 0) != CATALOG_VERSION:
        return []
    rows = payload.get("accounts")
    if not isinstance(rows, list):
        return []
    result: list[InstagramDestination] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        account_id = str(raw.get("id") or "").strip()
        if not account_id or account_id in seen:
            continue
        seen.add(account_id)
        result.append(
            InstagramDestination(
                id=account_id,
                username=str(raw.get("username") or "").strip(),
                account_type=str(raw.get("account_type") or "").strip(),
                page_id=str(raw.get("page_id") or "").strip(),
                page_name=str(raw.get("page_name") or "").strip(),
                auth_mode=str(raw.get("auth_mode") or "facebook_login").strip() or "facebook_login",
            )
        )
    return result


def instagram_account_for_key(config, key: str) -> InstagramDestination | None:
    value = str(key or "").strip()
    if value.startswith("instagram:"):
        account_id = value.split(":", 1)[1]
        for row in load_instagram_catalog():
            if row.id == account_id:
                return row
        # Backward-compatible fallback for a legacy encrypted single account.
        if account_id and account_id == str(getattr(config, "instagram_user_id", "") or ""):
            return InstagramDestination(
                id=account_id,
                username=str(getattr(config, "instagram_profile_name", "") or ""),
                auth_mode="legacy",
            )
    elif value == "instagram" and getattr(config, "instagram_user_id", ""):
        return InstagramDestination(
            id=str(config.instagram_user_id),
            username=str(getattr(config, "instagram_profile_name", "") or ""),
            auth_mode="legacy",
        )
    return None


def instagram_token_for(config, account: InstagramDestination) -> str:
    if account.page_id:
        page = config.facebook_page(account.page_id)
        if page is not None:
            return str(page.get("access_token") or "").strip()
    if account.id == str(getattr(config, "instagram_user_id", "") or ""):
        return str(getattr(config, "instagram_token", "") or "").strip()
    return ""


def destination_specs(config) -> list[DestinationSpec]:
    result: list[DestinationSpec] = []
    seen: set[str] = set()

    for row in getattr(config, "facebook_pages", []) or []:
        if not isinstance(row, dict):
            continue
        page_id = str(row.get("id") or "").strip()
        if not page_id or page_id in seen:
            continue
        key = f"facebook:{page_id}"
        seen.add(key)
        result.append(DestinationSpec(key, str(row.get("name") or page_id), "facebook"))

    catalog = load_instagram_catalog()
    for account in catalog:
        if account.key in seen:
            continue
        seen.add(account.key)
        result.append(DestinationSpec(account.key, account.label, "instagram"))

    legacy_id = str(getattr(config, "instagram_user_id", "") or "").strip()
    if legacy_id:
        legacy_key = f"instagram:{legacy_id}"
        if legacy_key not in seen:
            name = str(getattr(config, "instagram_profile_name", "") or legacy_id).strip()
            result.append(DestinationSpec(legacy_key, f"{name} (Instagram)", "instagram"))
            seen.add(legacy_key)

    if getattr(config, "threads_user_id", ""):
        result.append(
            DestinationSpec(
                "threads",
                str(getattr(config, "threads_profile_name", "") or "Threads"),
                "threads",
            )
        )
    if getattr(config, "linkedin_author_urn", ""):
        result.append(
            DestinationSpec(
                "linkedin",
                str(getattr(config, "linkedin_profile_name", "") or "LinkedIn"),
                "linkedin",
            )
        )
    telegram_rows = load_telegram_catalog()
    for row in telegram_rows:
        if row.key in seen:
            continue
        seen.add(row.key)
        result.append(DestinationSpec(row.key, row.label, "telegram"))

    legacy_chat = str(getattr(config, "telegram_chat_id", "") or "").strip()
    if legacy_chat:
        legacy_key = f"telegram:{legacy_chat}"
        if legacy_key not in seen:
            result.append(DestinationSpec(legacy_key, f"{legacy_chat} (Telegram)", "telegram"))
            seen.add(legacy_key)
    return result


def destination_labels(config) -> dict[str, str]:
    return {row.key: row.label for row in destination_specs(config)}


def destination_ready(config, key: str) -> bool:
    value = str(key or "").strip()
    if value.startswith("telegram:"):
        destination = telegram_destination_for_key(config, value)
        return bool(
            destination
            and getattr(config, "telegram_enabled", False)
            and getattr(config, "telegram_bot_token", "")
            and destination.chat_id
        )
    if value.startswith("instagram:"):
        account = instagram_account_for_key(config, value)
        return bool(
            account
            and getattr(config, "instagram_enabled", False)
            and instagram_token_for(config, account)
            and getattr(config, "meta_graph_version", "")
        )
    return bool(config.platform_ready(value))


def normalize_legacy_target_keys(config, keys: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    specs = destination_specs(config)
    instagram_keys = [row.key for row in specs if row.platform == "instagram"]
    telegram_keys = [row.key for row in specs if row.platform == "telegram"]
    legacy_chat = str(getattr(config, "telegram_chat_id", "") or "").strip()
    preferred_telegram = f"telegram:{legacy_chat}" if legacy_chat else ""
    if preferred_telegram not in telegram_keys:
        preferred_telegram = telegram_keys[0] if telegram_keys else ""
    for raw in keys:
        key = str(raw or "").strip()
        if key == "instagram":
            expanded = instagram_keys
        elif key == "telegram":
            expanded = [preferred_telegram] if preferred_telegram else []
        else:
            expanded = [key]
        for item in expanded:
            if item and item not in seen:
                seen.add(item)
                result.append(item)
    return result


def make_display_title(headline: str, final_text: str, *, limit: int = DISPLAY_TITLE_LIMIT) -> str:
    def clean(value: str) -> str:
        return " ".join(str(value or "").replace("\u00a0", " ").split()).strip()

    title = clean(headline)
    if not title:
        paragraphs = [clean(part) for part in str(final_text or "").split("\n\n")]
        title = next((part for part in paragraphs if part), "")
    if not title:
        title = "Матеріал без редакційного заголовка"
    cap = max(40, int(limit))
    if len(title) <= cap:
        return title
    return title[: cap - 1].rstrip(" ,.;:-") + "…"


class DestinationScheduleStore:
    def __init__(self, config, path: Path | None = None):
        self.config = config
        self.path = path or destination_schedules_path()
        self._rows = self._load()

    def _default(self) -> DestinationSchedule:
        return DestinationSchedule(
            int(getattr(self.config, "publish_start_hour", 9)),
            int(getattr(self.config, "publish_end_hour", 20)),
            int(getattr(self.config, "publish_interval_minutes", 60)),
        ).validate()

    def _load(self) -> dict[str, DestinationSchedule]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict) or int(payload.get("version") or 0) != SCHEDULE_VERSION:
            return {}
        source = payload.get("destinations")
        if not isinstance(source, dict):
            return {}
        result: dict[str, DestinationSchedule] = {}
        for key, raw in source.items():
            if not isinstance(raw, dict):
                continue
            try:
                result[str(key)] = DestinationSchedule(
                    int(raw.get("start_hour")),
                    int(raw.get("end_hour")),
                    int(raw.get("interval_minutes")),
                ).validate()
            except (TypeError, ValueError):
                continue
        return result

    def get(self, key: str) -> DestinationSchedule:
        return self._rows.get(str(key), self._default())

    def set(self, key: str, schedule: DestinationSchedule) -> None:
        self._rows[str(key)] = schedule.validate()

    def remove_missing(self, valid_keys: Iterable[str]) -> None:
        valid = {str(value) for value in valid_keys}
        self._rows = {key: value for key, value in self._rows.items() if key in valid}

    def save(self) -> Path:
        _atomic_json_write(
            self.path,
            {
                "version": SCHEDULE_VERSION,
                "updated_at": datetime.now(KYIV).isoformat(timespec="seconds"),
                "destinations": {key: asdict(value) for key, value in sorted(self._rows.items())},
            },
        )
        return self.path
