from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from ...paths import data_dir

_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class UsageEvent:
    timestamp: str
    backend: str
    task: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    elapsed_seconds: float
    success: bool
    detail: str = ""


def usage_path() -> Path:
    root = data_dir() / "v2"
    root.mkdir(parents=True, exist_ok=True)
    return root / "ai_usage.jsonl"


def record_usage(event: UsageEvent) -> None:
    line = json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":"))
    with _LOCK:
        with usage_path().open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _iter_events() -> Iterable[dict[str, object]]:
    path = usage_path()
    if not path.exists():
        return ()
    rows: list[dict[str, object]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except Exception:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
    except OSError:
        return ()
    return rows


def usage_summary(*, backend: str | None = None) -> dict[str, float | int]:
    now = datetime.now().astimezone()
    month_prefix = now.strftime("%Y-%m")
    day_prefix = now.strftime("%Y-%m-%d")
    result: dict[str, float | int] = {
        "today_cost": 0.0,
        "month_cost": 0.0,
        "today_prompt_tokens": 0,
        "today_completion_tokens": 0,
        "month_prompt_tokens": 0,
        "month_completion_tokens": 0,
        "today_requests": 0,
        "month_requests": 0,
        "month_errors": 0,
    }
    wanted = str(backend or "").casefold()
    for row in _iter_events():
        if wanted and str(row.get("backend") or "").casefold() != wanted:
            continue
        timestamp = str(row.get("timestamp") or "")
        if not timestamp.startswith(month_prefix):
            continue
        cost = float(row.get("cost_usd") or 0.0)
        prompt = int(row.get("prompt_tokens") or 0)
        completion = int(row.get("completion_tokens") or 0)
        result["month_cost"] = float(result["month_cost"]) + cost
        result["month_prompt_tokens"] = int(result["month_prompt_tokens"]) + prompt
        result["month_completion_tokens"] = int(result["month_completion_tokens"]) + completion
        result["month_requests"] = int(result["month_requests"]) + 1
        if not bool(row.get("success", True)):
            result["month_errors"] = int(result["month_errors"]) + 1
        if timestamp.startswith(day_prefix):
            result["today_cost"] = float(result["today_cost"]) + cost
            result["today_prompt_tokens"] = int(result["today_prompt_tokens"]) + prompt
            result["today_completion_tokens"] = int(result["today_completion_tokens"]) + completion
            result["today_requests"] = int(result["today_requests"]) + 1
    return result
