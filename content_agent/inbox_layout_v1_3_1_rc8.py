from __future__ import annotations

import json
import os
from pathlib import Path

from .paths import data_dir


DEFAULT_WIDTHS: dict[str, int] = {
    "id": 62,
    "status": 78,
    "title": 720,
    "topic": 112,
    "sources": 46,
    "published": 178,
    "score": 108,
    "history": 132,
}

_MIN_WIDTHS: dict[str, int] = {
    "id": 45,
    "status": 55,
    "title": 260,
    "topic": 75,
    "sources": 38,
    "published": 110,
    "score": 80,
    "history": 95,
}

_MAX_WIDTH = 1800
_FILE_NAME = "inbox_layout_v1_3_1_rc8.json"


def inbox_layout_path() -> Path:
    return data_dir() / _FILE_NAME


def normalize_widths(values: object) -> dict[str, int]:
    source = values if isinstance(values, dict) else {}
    result = dict(DEFAULT_WIDTHS)
    for key in DEFAULT_WIDTHS:
        try:
            value = int(source.get(key, result[key]))
        except (TypeError, ValueError):
            continue
        result[key] = max(_MIN_WIDTHS[key], min(_MAX_WIDTH, value))
    return result


def load_widths(path: Path | None = None) -> dict[str, int]:
    target = path or inbox_layout_path()
    if not target.exists():
        return dict(DEFAULT_WIDTHS)
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return dict(DEFAULT_WIDTHS)
    return normalize_widths(payload)


def save_widths(widths: dict[str, int], path: Path | None = None) -> dict[str, int]:
    target = path or inbox_layout_path()
    normalized = normalize_widths(widths)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, target)
    return normalized
