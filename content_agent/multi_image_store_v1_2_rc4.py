from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .paths import data_dir

_STORE_VERSION = 1
MAX_IMAGE_ATTACHMENTS = 10


class MultiImageStoreError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StoredImageAttachment:
    file_id: str
    name: str
    mime_type: str
    size: int
    drive_url: str


class MultiImageStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "multi_images_v1_2.json")

    def _read(self) -> dict[str, object]:
        if not self.path.exists():
            return {"version": _STORE_VERSION, "groups": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MultiImageStoreError("Список фото пошкоджений.") from exc
        if not isinstance(payload, dict) or int(payload.get("version", 0) or 0) != _STORE_VERSION:
            raise MultiImageStoreError("Список фото має непідтримуваний формат.")
        if not isinstance(payload.get("groups"), dict):
            raise MultiImageStoreError("Список фото не містить коректних груп.")
        return payload

    def _write(self, payload: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        try:
            with temporary.open("wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise MultiImageStoreError("Не вдалося зберегти список фото.") from exc
