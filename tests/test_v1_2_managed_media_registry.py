from __future__ import annotations

from pathlib import Path

import pytest

from content_agent.managed_media_registry import (
    ManagedMediaRegistry,
    ManagedMediaRegistryError,
)


def test_registry_tracks_only_explicitly_registered_files(tmp_path: Path) -> None:
    registry = ManagedMediaRegistry(tmp_path / "managed.json")
    assert not registry.is_managed("outside")

    registry.register(
        "file123",
        folder_id="folder123",
        group_id=7,
        name="photo.jpg",
    )

    assert registry.is_managed("file123")
    assert not registry.is_managed("outside")
    assert registry.details("file123") == {
        "folder_id": "folder123",
        "group_id": 7,
        "name": "photo.jpg",
        "created_at": registry.details("file123")["created_at"],
    }


def test_registry_remove_is_idempotent(tmp_path: Path) -> None:
    registry = ManagedMediaRegistry(tmp_path / "managed.json")
    registry.register("file123", folder_id="folder", group_id=1, name="a.jpg")
    registry.remove("file123")
    registry.remove("file123")
    assert not registry.is_managed("file123")


def test_registry_fails_closed_on_corruption(tmp_path: Path) -> None:
    path = tmp_path / "managed.json"
    path.write_text("broken", encoding="utf-8")
    registry = ManagedMediaRegistry(path)
    with pytest.raises(ManagedMediaRegistryError, match="пошкоджений"):
        registry.is_managed("file123")
