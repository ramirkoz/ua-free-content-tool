from __future__ import annotations

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
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[int, dict[str, object]]] = []

    def set_group_media(self, group_id: int, **kwargs: object) -> None:
        if self.fail:
            raise RuntimeError("database failure")
        self.calls.append((group_id, kwargs))


class _Client:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_file(self, file_id: str) -> None:
        self.deleted.append(file_id)


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


def _window(*, current_group_id: int, target_group_id: int, fail: bool = False) -> tuple[MainWindow, _Database, _Client]:
    window = MainWindow.__new__(MainWindow)
    database = _Database(fail=fail)
    client = _Client()
    window.db = database
    window.current_group_id = current_group_id
    window._media_target_group_id = target_group_id
    window.media_url_var = _Var()
    window.media_status_var = _Var()
    window.status_messages = []
    window.set_status = window.status_messages.append
    window._managed_drive_client = lambda: client
    return window, database, client


def test_upload_stays_bound_to_originating_group_after_editor_switch() -> None:
    window, database, client = _window(current_group_id=22, target_group_id=11)

    window._attach_uploaded_media(_upload())

    assert database.calls[0][0] == 11
    assert client.deleted == []
    assert window.media_url_var.value == ""
    assert "блока #11" in window.status_messages[-1]
    assert window._media_target_group_id is None


def test_upload_updates_visible_state_only_for_same_group() -> None:
    window, database, _client = _window(current_group_id=11, target_group_id=11)

    window._attach_uploaded_media(_upload())

    assert database.calls[0][0] == 11
    assert window.media_url_var.value.endswith("/file123/view")
    assert "Медіа готове" in window.media_status_var.value


def test_failed_attachment_deletes_only_new_managed_drive_file() -> None:
    window, _database, client = _window(current_group_id=11, target_group_id=11, fail=True)

    with pytest.raises(RuntimeError, match="database failure"):
        window._attach_uploaded_media(_upload())

    assert client.deleted == ["file123"]
    assert window._media_target_group_id is None
