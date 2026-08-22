from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .media_candidates import MediaCandidate, deduplicate_media_candidates
from .paths import data_dir

_STORE_VERSION = 1
_MAX_GROUPS = 500
_MAX_CANDIDATES_PER_GROUP = 50


class MediaCandidateStoreError(RuntimeError):
    pass


class MediaCandidateStore:
    """Small durable cache for discovered public media candidates.

    Candidate URLs are independent from publication state and tokens, so keeping
    them outside the main SQLite queue avoids a risky schema migration while the
    v1.2 workflow is still being validated.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "media_candidates.json")

    def _read(self) -> dict[str, object]:
        if not self.path.exists():
            return {"version": _STORE_VERSION, "groups": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MediaCandidateStoreError("Сховище медіакандидатів пошкоджене.") from exc
        if not isinstance(payload, dict) or int(payload.get("version", 0) or 0) != _STORE_VERSION:
            raise MediaCandidateStoreError("Сховище медіакандидатів має непідтримуваний формат.")
        groups = payload.get("groups")
        if not isinstance(groups, dict):
            raise MediaCandidateStoreError("Сховище медіакандидатів не містить коректного списку груп.")
        return payload

    def _write(self, payload: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        try:
            with temporary.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            if os.name != "nt":
                descriptor = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        except OSError as exc:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise MediaCandidateStoreError("Не вдалося зберегти медіакандидатів.") from exc

    @staticmethod
    def _decode(row: object) -> MediaCandidate | None:
        if not isinstance(row, dict):
            return None
        try:
            candidate = MediaCandidate(
                url=str(row.get("url") or ""),
                kind=str(row.get("kind") or "image"),
                source_label=str(row.get("source_label") or ""),
                origin=str(row.get("origin") or "stored"),
                mime_hint=str(row.get("mime_hint") or ""),
                width=max(0, int(row.get("width") or 0)),
                height=max(0, int(row.get("height") or 0)),
                score=max(0, int(row.get("score") or 0)),
            )
        except (TypeError, ValueError):
            return None
        if not candidate.url.startswith(("http://", "https://")):
            return None
        if candidate.kind not in {"image", "video"}:
            return None
        return candidate

    def list_group(self, group_id: int) -> list[MediaCandidate]:
        payload = self._read()
        groups = payload["groups"]
        assert isinstance(groups, dict)
        rows = groups.get(str(int(group_id)), [])
        if not isinstance(rows, list):
            return []
        decoded = [candidate for row in rows if (candidate := self._decode(row)) is not None]
        return deduplicate_media_candidates(decoded)[:_MAX_CANDIDATES_PER_GROUP]

    def save_group(self, group_id: int, candidates: Iterable[MediaCandidate]) -> int:
        payload = self._read()
        groups = payload["groups"]
        assert isinstance(groups, dict)
        normalized = deduplicate_media_candidates(candidates)[:_MAX_CANDIDATES_PER_GROUP]
        key = str(int(group_id))
        if normalized:
            groups[key] = [asdict(candidate) for candidate in normalized]
        else:
            groups.pop(key, None)
        if len(groups) > _MAX_GROUPS:
            for stale_key in list(groups)[: len(groups) - _MAX_GROUPS]:
                groups.pop(stale_key, None)
        self._write(payload)
        return len(normalized)

    def clear_group(self, group_id: int) -> None:
        payload = self._read()
        groups = payload["groups"]
        assert isinstance(groups, dict)
        if groups.pop(str(int(group_id)), None) is not None:
            self._write(payload)
