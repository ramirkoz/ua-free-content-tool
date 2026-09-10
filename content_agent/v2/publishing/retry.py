from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping


_UNKNOWN_MARKERS = (
    "результат невідом",
    "unknown outcome",
    "outcome unknown",
    "перевірте платформу вручну",
    "результат запиту невідом",
    "could not determine whether",
)

# These are metadata keys that are safe to carry into a new, independent retry.
# Runtime/publication-side-effect state is deliberately NOT copied.
_SAFE_PROGRESS_KEYS = {
    "display_title",
    "donation_enabled",
    "donation_mode",
    "donation_text",
}

_SIDE_EFFECT_HINTS = (
    "remote_id",
    "remote_ids",
    "post_id",
    "photo_ids",
    "image_urns",
    "children",
    "container_id",
    "asset",
    "media_sent",
    "sent_parts",
    "published_parts",
)


@dataclass(slots=True)
class RetryAssessment:
    retryable: bool
    reason: str = ""
    progress: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetryBatchResult:
    group_id: int
    created_batch_ids: list[int] = field(default_factory=list)
    created_platforms: list[str] = field(default_factory=list)
    blocked: dict[str, str] = field(default_factory=dict)


def _as_dict(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        value = json.loads(str(raw or "{}"))
    except Exception:
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return value is not None


def _has_uncertain_side_effect(progress: Mapping[str, Any]) -> str:
    # Explicit started/completed pairs are the strongest signal that a platform
    # write may have begun. A manual retry must fail closed in that case.
    for key, value in progress.items():
        lowered = str(key).casefold()
        if not lowered.endswith("started") or not _truthy(value):
            continue
        completed_key = str(key)[: -len("started")] + "completed"
        if not _truthy(progress.get(completed_key)):
            return f"Зафіксовано незавершений зовнішній запис ({key})."

    for key, value in progress.items():
        lowered = str(key).casefold()
        if any(hint in lowered for hint in _SIDE_EFFECT_HINTS) and _truthy(value):
            return f"Є ознака часткового зовнішнього запису ({key})."
    return ""


def sanitize_retry_progress(raw: object, *, requested_at: str, old_target_id: int, old_batch_id: int) -> dict[str, Any]:
    source = _as_dict(raw)
    clean = {key: source[key] for key in _SAFE_PROGRESS_KEYS if key in source}
    clean.update(
        {
            "publish_now": True,
            "publish_now_requested_at": requested_at,
            "manual_retry": True,
            "retry_of_target_id": int(old_target_id),
            "retry_of_batch_id": int(old_batch_id),
        }
    )
    return clean


def assess_failed_target(row: Mapping[str, Any] | Any) -> RetryAssessment:
    def get(name: str, default: Any = "") -> Any:
        try:
            return row[name]
        except Exception:
            return getattr(row, name, default)

    status = str(get("target_status", get("status", "")) or "").casefold()
    batch_status = str(get("batch_status", "completed") or "").casefold()
    remote_id = str(get("remote_id", "") or "").strip()
    error = str(get("last_error", "") or "").strip()
    progress = _as_dict(get("progress_json", get("progress", {})))

    if status != "failed":
        return RetryAssessment(False, "Повтор доступний тільки для публікації зі статусом «помилка».", progress)
    if batch_status and batch_status != "completed":
        return RetryAssessment(False, "Попередня спроба ще не є завершеною.", progress)
    if remote_id:
        return RetryAssessment(False, "Платформа вже повернула remote ID; автоматичний повтор може створити дубль.", progress)
    low_error = error.casefold()
    if any(marker in low_error for marker in _UNKNOWN_MARKERS):
        return RetryAssessment(False, "Результат попередньої зовнішньої операції невідомий. Спочатку потрібна ручна перевірка платформи.", progress)
    side_effect = _has_uncertain_side_effect(progress)
    if side_effect:
        return RetryAssessment(False, side_effect + " Автоматичний повтор заблоковано проти дублювання.", progress)
    return RetryAssessment(True, "Попередня спроба завершилася відомою помилкою до підтвердженої публікації.", progress)
