from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

from .media_candidates import MediaCandidate
from .paths import data_dir


class SourceMediaHintStore:
    """Small atomic sidecar preserving source media visible during collection."""

    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "source_media_hints_v1_2.json")

    def _load(self) -> dict[str, list[dict[str, object]]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _row(item: MediaCandidate) -> dict[str, object]:
        return {
            "url": item.url,
            "kind": item.kind,
            "source_label": item.source_label,
            "origin": item.origin,
            "mime_hint": item.mime_hint,
            "width": item.width,
            "height": item.height,
            "score": item.score,
        }

    @staticmethod
    def _candidate(row: object) -> MediaCandidate | None:
        if not isinstance(row, dict):
            return None
        url = str(row.get("url") or "")
        if not url.startswith(("http://", "https://")):
            return None
        return MediaCandidate(
            url=url,
            kind=str(row.get("kind") or "image"),
            source_label=str(row.get("source_label") or ""),
            origin=str(row.get("origin") or "stored"),
            mime_hint=str(row.get("mime_hint") or ""),
            width=int(row.get("width") or 0),
            height=int(row.get("height") or 0),
            score=int(row.get("score") or 0),
        )

    def save(self, article_url: str, candidates: Iterable[MediaCandidate]) -> None:
        key = str(article_url or "").strip()
        rows = [self._row(item) for item in candidates]
        if not key or not rows:
            return
        payload = self._load()
        payload[key] = rows[:24]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def get(self, article_url: str) -> list[MediaCandidate]:
        rows = self._load().get(str(article_url or "").strip(), [])
        result: list[MediaCandidate] = []
        for row in rows:
            candidate = self._candidate(row)
            if candidate is not None:
                result.append(candidate)
        return result
