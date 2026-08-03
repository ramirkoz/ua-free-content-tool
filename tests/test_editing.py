from __future__ import annotations

from types import SimpleNamespace

from content_agent.ui.editing import _dispatch, _handle_keypress


class FakeEntry:
    def __init__(self, value: str = "") -> None:
        self.value = value
        self.insert_pos = len(value)
        self.selection: tuple[int, int] | None = None
        self.clipboard = ""

    def winfo_class(self) -> str:
        return "TEntry"

    def clipboard_get(self) -> str:
        return self.clipboard

    def clipboard_clear(self) -> None:
        self.clipboard = ""

    def clipboard_append(self, text: str) -> None:
        self.clipboard += text

    def selection_present(self) -> bool:
        return self.selection is not None

    def index(self, index: str) -> int:
        if index == "insert":
            return self.insert_pos
        if index == "sel.first" and self.selection:
            return self.selection[0]
        if index == "sel.last" and self.selection:
            return self.selection[1]
        raise ValueError(index)

    def get(self) -> str:
        return self.value

    def delete(self, first: str | int, last: str | int) -> None:
        start = self.index(first) if isinstance(first, str) else first
        end = self.index(last) if isinstance(last, str) else last
        self.value = self.value[:start] + self.value[end:]
        self.insert_pos = start
        self.selection = None

    def insert(self, index: int, text: str) -> None:
        self.value = self.value[:index] + text + self.value[index:]
        self.insert_pos = index + len(text)

    def selection_range(self, first: int, last: str) -> None:
        assert last == "end"
        self.selection = (first, len(self.value))

    def icursor(self, index: str) -> None:
        assert index == "end"
        self.insert_pos = len(self.value)


def test_ctrl_v_uses_physical_keycode_even_with_non_latin_keysym() -> None:
    widget = FakeEntry("abc")
    widget.clipboard = "-вставлено-"
    event = SimpleNamespace(widget=widget, state=0x0004, keycode=86, keysym="м")
    assert _handle_keypress(event) == "break"
    assert widget.value == "abc-вставлено-"


def test_paste_replaces_selected_text() -> None:
    widget = FakeEntry("old-value")
    widget.selection = (0, 3)
    widget.clipboard = "new"
    assert _dispatch(widget, "paste") == "break"
    assert widget.value == "new-value"


def test_select_all_is_layout_independent() -> None:
    widget = FakeEntry("token")
    event = SimpleNamespace(widget=widget, state=0x0004, keycode=65, keysym="ф")
    assert _handle_keypress(event) == "break"
    assert widget.selection == (0, 5)
