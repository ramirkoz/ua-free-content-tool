from __future__ import annotations

from pathlib import Path


def _read_version() -> str:
    candidates = (
        Path(__file__).resolve().parent.parent / "VERSION.txt",
        Path.cwd() / "VERSION.txt",
    )
    for path in candidates:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return "2.0.0-unknown"


APP_VERSION = _read_version()
