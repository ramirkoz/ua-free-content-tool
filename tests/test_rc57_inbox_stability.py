from __future__ import annotations

import inspect
from pathlib import Path

import content_agent
from content_agent.v2.ui.tabs.inbox import InboxTabController


class FakeTree:
    def __init__(self):
        self.order = ["a", "b", "c"]
        self.values = {
            "a": {"sources": "1", "published": "10:00", "title": "A", "topic": "Новини"},
            "b": {"sources": "5", "published": "09:00", "title": "B", "topic": "Новини"},
            "c": {"sources": "3", "published": "11:00", "title": "C", "topic": "Новини"},
        }

    def get_children(self):
        return tuple(self.order)

    def set(self, iid, column):
        return self.values[iid][column]

    def move(self, iid, _parent, index):
        self.order.remove(iid)
        self.order.insert(index, iid)


def _controller(tmp_path: Path) -> InboxTabController:
    obj = object.__new__(InboxTabController)
    obj.tree = FakeTree()
    obj._sort_path = tmp_path / "sort.json"
    obj._sort_column = "sources"
    obj._sort_descending = True
    return obj


def test_rc57_version_alignment_is_retained_across_newer_rcs():
    version = Path("VERSION.txt").read_text(encoding="utf-8").strip()
    public_version = Path("PUBLIC_VERSION.txt").read_text(encoding="utf-8").strip()
    assert version == public_version == content_agent.__version__
    assert version.startswith("2.0.0-rc")
    assert int(version.rsplit("rc", 1)[1]) >= 57


def test_rc57_sources_sort_is_reapplied_after_refresh_order():
    obj = _controller(Path("."))
    obj._apply_sort()
    assert obj.tree.order == ["b", "c", "a"]


def test_rc57_sort_choice_persists(tmp_path):
    obj = _controller(tmp_path)
    obj._save_sort_state()
    restored = object.__new__(InboxTabController)
    restored._sort_path = obj._sort_path
    restored._sort_column = "published"
    restored._sort_descending = False
    restored._load_sort_state()
    assert restored._sort_column == "sources"
    assert restored._sort_descending is True


def test_rc57_refresh_reapplies_sort_before_restoring_viewport():
    source = inspect.getsource(InboxTabController.refresh)
    assert source.index("self._apply_sort()") < source.index("existing = [iid for iid in selected_before")
    assert "viewport_anchors" in source
    assert "next((iid for iid in viewport_anchors" in source


def test_rc57_no_new_numbered_window_layer():
    root = Path(__file__).resolve().parents[1] / "content_agent"
    assert not list(root.rglob("*window_rc57*.py"))
