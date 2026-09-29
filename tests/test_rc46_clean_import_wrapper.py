from __future__ import annotations

from pathlib import Path

from content_agent.clean_import import _locate_old_data
from content_agent.v2.storage.factory import create_database


def _make_old_database(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    create_database(path)
    return path


def test_locator_accepts_data_folder(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    db = _make_old_database(data / "content_agent.sqlite3")
    root, found = _locate_old_data(data)
    assert root == data.resolve()
    assert found == db.resolve()


def test_locator_accepts_application_folder(tmp_path: Path) -> None:
    app = tmp_path / "UA_FREE_Content_Tool"
    data = app / "Data"
    db = _make_old_database(data / "content_agent.sqlite3")
    root, found = _locate_old_data(app)
    assert root == data.resolve()
    assert found == db.resolve()


def test_locator_accepts_outer_extracted_portable_wrapper(tmp_path: Path) -> None:
    wrapper = tmp_path / "UA_FREE_Content_Tool_v2.0.0-rc44_Windows_Portable_MANUAL_TEST"
    data = wrapper / "UA_FREE_Content_Tool" / "Data"
    db = _make_old_database(data / "content_agent.sqlite3")
    root, found = _locate_old_data(wrapper)
    assert root == data.resolve()
    assert found == db.resolve()


def test_locator_accepts_versioned_app_folder_one_level_down(tmp_path: Path) -> None:
    wrapper = tmp_path / "old-package"
    data = wrapper / "UA_FREE_Content_Tool_v2.0.0-rc40" / "Data"
    db = _make_old_database(data / "content_agent.sqlite3")
    root, found = _locate_old_data(wrapper)
    assert root == data.resolve()
    assert found == db.resolve()
