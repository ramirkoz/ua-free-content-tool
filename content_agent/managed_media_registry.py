from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .paths import data_dir

_STORE_VERSION = 1
_MAX_FILES = 2000


class ManagedMediaRegistryError(RuntimeError):
    pass


class ManagedMediaRegistry:
    """Durable allow-list of Drive files created by this application.

    The publication worker may delete only IDs recorded here. Existing user files
    and legacy manually pasted Drive links remain outside this allow-list.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "managed_media.json")

    def _read(self) -> dict[str, object]:
        if not self.path.exists():
            return {"version": _STORE_VERSION, "files": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ManagedMediaRegistryError("Реєстр керованих медіафайлів пошкоджений.") from exc
        if not isinstance(payload, dict) or int(payload.get("version", 0) or 0) != _STORE_VERSION:
            raise ManagedMediaRegistryError("Реєстр керованих медіафайлів має непідтримуваний формат.")
        files = payload.get("files")
        if not isinstance(files, dict):
            raise ManagedMediaRegistryError("Реєстр керованих медіафайлів не містить коректного списку.")
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
            raise ManagedMediaRegistryError("Не вдалося зберегти реєстр керованих медіафайлів.") from exc

    def register(
        self,
        file_id: str,
        *,
        folder_id: str,
        group_id: int,
        name: str,
    ) -> None:
        value = str(file_id or "").strip()
        if not value:
            raise ManagedMediaRegistryError("Google Drive не повернув ID керованого файла.")
        payload = self._read()
        files = payload["files"]
        assert isinstance(files, dict)
        files[value] = {
            "folder_id": str(folder_id or ""),
            "group_id": int(group_id),
            "name": str(name or "media"),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if len(files) > _MAX_FILES:
            ordered = sorted(
                files,
                key=lambda key: str(files[key].get("created_at") or "")
                if isinstance(files[key], dict)
                else "",
            )
            for stale in ordered[: len(files) - _MAX_FILES]:
                files.pop(stale, None)
        self._write(payload)

    def is_managed(self, file_id: str) -> bool:
        value = str(file_id or "").strip()
        if not value:
            return False
        payload = self._read()
        files = payload["files"]
        assert isinstance(files, dict)
        return value in files

    def remove(self, file_id: str) -> None:
        value = str(file_id or "").strip()
        if not value:
            return
        payload = self._read()
        files = payload["files"]
        assert isinstance(files, dict)
        if files.pop(value, None) is not None:
            self._write(payload)

    def details(self, file_id: str) -> dict[str, object] | None:
        value = str(file_id or "").strip()
        if not value:
            return None
        payload = self._read()
        files = payload["files"]
        assert isinstance(files, dict)
        row = files.get(value)
        return dict(row) if isinstance(row, dict) else None
