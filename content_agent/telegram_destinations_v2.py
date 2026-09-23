from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlencode

from .destinations_v1_4 import TelegramDestination
from .platform_setup import PlatformSetupError, _get_json


@dataclass(slots=True, frozen=True)
class TelegramDiscoveryResult:
    destinations: tuple[TelegramDestination, ...]
    bot_id: str
    bot_username: str
    updates_seen: int = 0
    webhook_active: bool = False
    note: str = ""


def _bot_identity(token: str) -> tuple[str, str]:
    payload = _get_json(f"https://api.telegram.org/bot{token}/getMe")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise PlatformSetupError("Telegram не повернув дані бота.")
    bot_id = str(result.get("id") or "").strip()
    username = str(result.get("username") or "").strip()
    if not bot_id:
        raise PlatformSetupError("Telegram не повернув ID бота.")
    return bot_id, username


def _chat_from_target(token: str, target: str, bot_id: str) -> TelegramDestination | None:
    value = str(target or "").strip()
    if not value:
        return None
    chat = _get_json(
        f"https://api.telegram.org/bot{token}/getChat?{urlencode({'chat_id': value})}"
    ).get("result")
    if not isinstance(chat, dict):
        return None
    chat_type = str(chat.get("type") or "").strip()
    if chat_type != "channel":
        return None
    chat_id = str(chat.get("id") or "").strip()
    if not chat_id:
        return None
    member = _get_json(
        f"https://api.telegram.org/bot{token}/getChatMember?{urlencode({'chat_id': chat_id, 'user_id': bot_id})}"
    ).get("result")
    if not isinstance(member, dict):
        return None
    status = str(member.get("status") or "").strip()
    can_post = bool(member.get("can_post_messages")) or status == "creator"
    if status not in {"administrator", "creator"} or not can_post:
        return None
    return TelegramDestination(
        chat_id=chat_id,
        title=str(chat.get("title") or chat.get("username") or chat_id).strip(),
        username=str(chat.get("username") or "").strip().lstrip("@"),
        chat_type=chat_type,
        member_status=status,
        can_post_messages=can_post,
    )


def inspect_telegram_destination(token: str, target: str) -> tuple[TelegramDestination, str, str]:
    token = str(token or "").strip()
    target = str(target or "").strip()
    if not token or not target:
        raise PlatformSetupError("Вставте Telegram bot token і @назву або ID каналу.")
    bot_id, bot_username = _bot_identity(token)
    destination = _chat_from_target(token, target, bot_id)
    if destination is None:
        raise PlatformSetupError(
            "Канал не підтверджено. Бот має бути адміністратором саме каналу і мати право публікувати повідомлення.",
            http_status=403,
        )
    return destination, bot_id, bot_username


def _candidate_targets_from_updates(payload: dict[str, object]) -> tuple[set[str], int]:
    rows = payload.get("result")
    if not isinstance(rows, list):
        return set(), 0
    targets: set[str] = set()
    for update in rows:
        if not isinstance(update, dict):
            continue
        for key in ("channel_post", "edited_channel_post"):
            message = update.get(key)
            if isinstance(message, dict):
                chat = message.get("chat")
                if isinstance(chat, dict) and str(chat.get("type") or "") == "channel" and chat.get("id") is not None:
                    targets.add(str(chat.get("id")))
        membership = update.get("my_chat_member")
        if isinstance(membership, dict):
            chat = membership.get("chat")
            if isinstance(chat, dict) and str(chat.get("type") or "") == "channel" and chat.get("id") is not None:
                targets.add(str(chat.get("id")))
    return targets, len(rows)


def discover_telegram_destinations(
    token: str,
    known_targets: Iterable[str] = (),
) -> TelegramDiscoveryResult:
    """Discover publishable Telegram channels visible to the Bot API.

    Telegram Bot API has no method that enumerates every channel a bot administers.
    This function combines the persistent local catalog with channel chats visible
    in the bot's recent update queue, then verifies current administrator/posting
    rights with getChatMember. Existing known targets are re-verified as well.
    """

    token = str(token or "").strip()
    if not token:
        raise PlatformSetupError("Вставте Telegram bot token.")
    bot_id, bot_username = _bot_identity(token)

    candidates = {str(item or "").strip() for item in known_targets if str(item or "").strip()}
    updates_seen = 0
    webhook_active = False
    note = ""

    try:
        webhook = _get_json(f"https://api.telegram.org/bot{token}/getWebhookInfo").get("result")
        webhook_url = str(webhook.get("url") or "").strip() if isinstance(webhook, dict) else ""
        webhook_active = bool(webhook_url)
    except PlatformSetupError:
        webhook_active = False

    if webhook_active:
        note = (
            "У бота активний webhook, тому Bot API не дозволяє getUpdates. "
            "Перевірено раніше збережені канали; інші можна додати вручну за @username або ID."
        )
    else:
        try:
            query = urlencode(
                {
                    "limit": 100,
                    "timeout": 0,
                    "allowed_updates": json.dumps(
                        ["channel_post", "edited_channel_post", "my_chat_member"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            )
            updates = _get_json(f"https://api.telegram.org/bot{token}/getUpdates?{query}")
            recent, updates_seen = _candidate_targets_from_updates(updates)
            candidates.update(recent)
            if updates_seen >= 100:
                note = (
                    "Telegram повернув ліміт 100 останніх pending updates. Знайдені канали збережено; "
                    "тихі або старі канали додайте вручну один раз."
                )
        except PlatformSetupError as exc:
            note = (
                "Автоматичний пошук через getUpdates недоступний: " + str(exc) + ". "
                "Раніше збережені канали перевірено; інші можна додати вручну."
            )

    verified: list[TelegramDestination] = []
    seen: set[str] = set()
    for target in sorted(candidates):
        try:
            destination = _chat_from_target(token, target, bot_id)
        except PlatformSetupError:
            destination = None
        if destination is None or destination.chat_id in seen:
            continue
        seen.add(destination.chat_id)
        verified.append(destination)

    verified.sort(key=lambda item: (item.title.casefold(), item.chat_id))
    return TelegramDiscoveryResult(
        destinations=tuple(verified),
        bot_id=bot_id,
        bot_username=bot_username,
        updates_seen=updates_seen,
        webhook_active=webhook_active,
        note=note,
    )
