from __future__ import annotations

from types import SimpleNamespace

import pytest

from content_agent.google_drive import DriveMediaInfo
from content_agent.managed_media_drive import ManagedMediaUpload
from content_agent.ui.v1_2_combined_window import MainWindow


class _Var:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


class _Database:
    def __init__(self, fail: bool = False, previous_file_id: str = "") -> None:
        self.fail = fail
        self.previous_file_id = previous_file_id
        self.calls: list[tuple[int, dict[str, object]]] = []

    def get_group(self, group_id: int) -> object:
        return SimpleNamespace(media_file_id=self.previous_file_id)

    def set_group_media(self, group_id: int, **kwargs: object) -> None:
        if self.fail:
            raise RuntimeError("database failure")
        self.calls.append((group_id, kwargs))


class _Client:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_file(self, file_id: str) -> None:
        self.deleted.append(file_id)


class _Registry:
    def __init__(self) -> None:
        self.files: set[str] = set()
        self.removed: list[str] = []

    def is_managed(self, file_id: str) -> bool:
        return file_id in self.files

    def register(self, file_id: str, **_kwargs: object) -> None:
        self.files.add(file_id)

    def remove(self, file_id: str) -> None:
        self.files.discard(file_id)
        self.removed.append(file_id)


class _Messages:
    def __init__(self, answer: bool = False) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def askyesno(self, _title: str, text: str, **_kwargs: object) -> bool:
        self.prompts.append(text)
        return self.answer


def _upload() -> ManagedMediaUpload:
    return ManagedMediaUpload(
        folder_id="folder123",
        info=DriveMediaInfo(
            file_id="file123",
            name="photo.jpg",
            mime_type="image/jpeg",
            size=1024,
            kind="image",
            can_download=True,
            can_delete=True,
            can_share=True,
            public_url="",
            public_direct=False,
        ),
    )


def _window(
    *,
    current_group_id: int,
    target_group_id: int,
    fail: bool = False,
    previous_file_id: str = "",
) -> tuple[MainWindow, _Database, _Client, _Registry]:
    window = MainWindow.__new__(MainWindow)
    database = _Database(fail=fail, previous_file_id=previous_file_id)
    client = _Client()
    registry = _Registry()
    window.db = database
    window.current_group_id = current_group_id
    window._media_target_group_id = target_group_id
    window.media_url_var = _Var()
    window.media_status_var = _Var()
    window.status_messages = []
    window.set_status = window.status_messages.append
    window._managed_drive_client = lambda: client
    window.managed_media_registry = registry
    window.msg = _Messages()
    window.root = object()
    return window, database, client, registry


def test_upload_stays_bound_to_originating_group_after_editor_switch() -> None:
    window, database, client, registry = _window(current_group_id=22, target_group_id=11)

    window._attach_uploaded_media(_upload())

    assert database.calls[0][0] == 11
    assert client.deleted == []
    assert registry.is_managed("file123")
    assert window.media_url_var.value == ""
    assert "блока #11" in window.status_messages[-1]
    assert window._media_target_group_id is None


def test_upload_updates_visible_state_only_for_same_group() -> None:
    window, database, _client, registry = _window(current_group_id=11, target_group_id=11)

    window._attach_uploaded_media(_upload())

    assert database.calls[0][0] == 11
    assert registry.is_managed("file123")
    assert window.media_url_var.value.endswith("/file123/view")
    assert "Медіа готове" in window.media_status_var.value


def test_failed_attachment_unregisters_and_deletes_only_new_file() -> None:
    window, _database, client, registry = _window(
        current_group_id=11,
        target_group_id=11,
        fail=True,
    )

    with pytest.raises(RuntimeError, match="database failure"):
        window._attach_uploaded_media(_upload())

    assert client.deleted == ["file123"]
    assert not registry.is_managed("file123")
    assert window._media_target_group_id is None


def test_external_previous_file_is_never_offered_for_deletion() -> None:
    window, _database, _client, _registry = _window(
        current_group_id=11,
        target_group_id=11,
        previous_file_id="external123",
    )

    window._attach_uploaded_media(_upload())

    assert window.msg.prompts == []
