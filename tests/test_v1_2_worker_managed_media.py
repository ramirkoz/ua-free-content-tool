from __future__ import annotations

from pathlib import Path

from content_agent.google_drive import DriveMediaInfo
from content_agent.managed_media_registry import ManagedMediaRegistry
from content_agent.worker_v1_2 import ManagedCleanupDriveProxy


class _Drive:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.removed: list[tuple[str, str]] = []

    def ensure_public_for_threads(self, info: DriveMediaInfo) -> str:
        return "permission123"

    def remove_permission(self, file_id: str, permission_id: str) -> None:
        self.removed.append((file_id, permission_id))

    def delete_file(self, file_id: str) -> None:
        self.deleted.append(file_id)


def _info(file_id: str) -> DriveMediaInfo:
    return DriveMediaInfo(
        file_id=file_id,
        name="photo.jpg",
        mime_type="image/jpeg",
        size=4,
        kind="image",
        can_download=True,
        can_delete=True,
        can_share=True,
        public_url="",
        public_direct=False,
    )


def test_managed_file_is_deleted_and_removed_from_registry(tmp_path: Path) -> None:
    registry = ManagedMediaRegistry(tmp_path / "managed.json")
    registry.register("managed123", folder_id="folder", group_id=1, name="photo.jpg")
    drive = _Drive()
    proxy = ManagedCleanupDriveProxy(drive, registry)  # type: ignore[arg-type]

    proxy.delete_file("managed123")

    assert drive.deleted == ["managed123"]
    assert not registry.is_managed("managed123")


def test_external_file_is_not_deleted_and_temporary_permission_is_removed(tmp_path: Path) -> None:
    registry = ManagedMediaRegistry(tmp_path / "managed.json")
    drive = _Drive()
    proxy = ManagedCleanupDriveProxy(drive, registry)  # type: ignore[arg-type]
    info = _info("external123")

    assert proxy.ensure_public_for_threads(info) == "permission123"
    proxy.delete_file(info.file_id)

    assert drive.deleted == []
    assert drive.removed == [("external123", "permission123")]


def test_external_file_without_threads_permission_is_only_detached(tmp_path: Path) -> None:
    registry = ManagedMediaRegistry(tmp_path / "managed.json")
    drive = _Drive()
    proxy = ManagedCleanupDriveProxy(drive, registry)  # type: ignore[arg-type]

    proxy.delete_file("external123")

    assert drive.deleted == []
    assert drive.removed == []
