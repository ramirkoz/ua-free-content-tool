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

    @classmethod
    def from_mapping(cls, value: object) -> "StoredImageAttachment":
        if not isinstance(value, dict):
            raise MultiImageStoreError("Збережений список фото має некоректний формат.")
        file_id = str(value.get("file_id") or "").strip()
        mime_type = str(value.get("mime_type") or "").strip().casefold()
        if not file_id or not mime_type.startswith("image/"):
            raise MultiImageStoreError("У списку кількох медіа дозволені лише фото.")
        return cls(
            file_id=file_id,
            name=str(value.get("name") or "image"),
            mime_type=mime_type,
            size=max(0, int(value.get("size") or 0)),
            drive_url=str(value.get("drive_url") or ""),
        )


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

    def list_group(self, group_id: int) -> list[StoredImageAttachment]:
        payload = self._read()
        groups = payload["groups"]
        assert isinstance(groups, dict)
        raw = groups.get(str(int(group_id)), [])
        if not isinstance(raw, list):
            raise MultiImageStoreError("Список фото цього блока пошкоджений.")
        return [StoredImageAttachment.from_mapping(item) for item in raw][:MAX_IMAGE_ATTACHMENTS]

    def set_group(self, group_id: int, items: list[StoredImageAttachment]) -> None:
        if len(items) > MAX_IMAGE_ATTACHMENTS:
            raise MultiImageStoreError(f"До однієї публікації можна додати не більше {MAX_IMAGE_ATTACHMENTS} фото.")
        unique: list[StoredImageAttachment] = []
        seen: set[str] = set()
        for item in items:
            if not item.mime_type.casefold().startswith("image/"):
                raise MultiImageStoreError("Кілька медіафайлів дозволені тільки для зображень.")
            if not item.file_id or item.file_id in seen:
                continue
            seen.add(item.file_id)
            unique.append(item)
        payload = self._read()
        groups = payload["groups"]
        assert isinstance(groups, dict)
        key = str(int(group_id))
        if unique:
            groups[key] = [asdict(item) for item in unique]
        else:
            groups.pop(key, None)
        self._write(payload)

    def append(self, group_id: int, item: StoredImageAttachment) -> list[StoredImageAttachment]:
        current = self.list_group(group_id)
        if any(row.file_id == item.file_id for row in current):
            return current
        if len(current) >= MAX_IMAGE_ATTACHMENTS:
            raise MultiImageStoreError(f"До однієї публікації можна додати не більше {MAX_IMAGE_ATTACHMENTS} фото.")
        current.append(item)
        self.set_group(group_id, current)
        return current

    def remove(self, group_id: int, file_id: str) -> list[StoredImageAttachment]:
        current = [item for item in self.list_group(group_id) if item.file_id != str(file_id)]
        self.set_group(group_id, current)
        return current

    def clear_group(self, group_id: int) -> list[StoredImageAttachment]:
        current = self.list_group(group_id)
        self.set_group(group_id, [])
        return current
