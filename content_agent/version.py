from __future__ import annotations

from pathlib import Path

from .paths import runtime_dir


def _read_version() -> str:
    candidates = (
        runtime_dir() / "VERSION.txt",
        Path.cwd() / "VERSION.txt",
        Path(__file__).resolve().parent.parent / "VERSION.txt",
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
