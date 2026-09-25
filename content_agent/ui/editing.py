from __future__ import annotations

import tkinter as tk
from typing import Any

_EDITABLE_CLASSES = {"TEntry", "Entry", "Text", "TCombobox", "Spinbox", "TSpinbox"}
_CONTROL_MASK = 0x0004
_SHIFT_MASK = 0x0001
_KEYCODE_ACTIONS = {
    65: "select_all",  # A
    67: "copy",        # C
    86: "paste",       # V
    88: "cut",         # X
}
_KEYSYM_ACTIONS = {
    "a": "select_all",
    "c": "copy",
    "v": "paste",
    "x": "cut",
}


def install_edit_support(root: tk.Misc) -> None:
    """Install layout-independent clipboard shortcuts and a Ukrainian context menu."""
    root.bind_all("<KeyPress>", _handle_keypress, add="+")
    root.bind_all("<Shift-Insert>", lambda event: _dispatch(event.widget, "paste"), add="+")
    root.bind_all("<Control-Insert>", lambda event: _dispatch(event.widget, "copy"), add="+")
    root.bind_all("<Shift-Delete>", lambda event: _dispatch(event.widget, "cut"), add="+")
    for widget_class in sorted(_EDITABLE_CLASSES):
        root.bind_class(widget_class, "<Button-3>", _show_context_menu, add="+")


def _handle_keypress(event: Any) -> str | None:
    widget = getattr(event, "widget", None)
    if not _is_editable(widget):
        return None
    state = int(getattr(event, "state", 0))
    if not state & _CONTROL_MASK:
        return None
    keycode = int(getattr(event, "keycode", 0) or 0)
    keysym = str(getattr(event, "keysym", "")).lower()
    action = _KEYCODE_ACTIONS.get(keycode) or _KEYSYM_ACTIONS.get(keysym)
    if action is None:
        return None
    return _dispatch(widget, action)


def _dispatch(widget: Any, action: str) -> str | None:
    if not _is_editable(widget):
        return None
    try:
        if action == "select_all":
            _select_all(widget)
        elif action == "copy":
            _copy(widget)
        elif action == "cut":
            if _copy(widget):
                _delete_selection(widget)
        elif action == "paste":
            text = widget.clipboard_get()
            _replace_selection(widget, text)
        else:
            return None
    except (tk.TclError, AttributeError, TypeError):
        return "break"
    return "break"


def _is_editable(widget: Any) -> bool:
    if widget is None or not hasattr(widget, "winfo_class"):
        return False
    try:
        return widget.winfo_class() in _EDITABLE_CLASSES
    except tk.TclError:
        return False


def _is_text(widget: Any) -> bool:
    return widget.winfo_class() == "Text"


def _selection(widget: Any) -> str | None:
    if _is_text(widget):
        ranges = widget.tag_ranges("sel")
        if not ranges:
            return None
        return str(widget.get("sel.first", "sel.last"))
    try:
        if not widget.selection_present():
            return None
        first = int(widget.index("sel.first"))
        last = int(widget.index("sel.last"))
        return str(widget.get())[first:last]
    except (tk.TclError, ValueError):
        return None


def _copy(widget: Any) -> bool:
    selected = _selection(widget)
    if selected is None:
        return False
    widget.clipboard_clear()
    widget.clipboard_append(selected)
    return True


def _delete_selection(widget: Any) -> None:
    if _is_text(widget):
        if widget.tag_ranges("sel"):
            widget.delete("sel.first", "sel.last")
        return
    try:
        if widget.selection_present():
            widget.delete("sel.first", "sel.last")
    except tk.TclError:
        return


def _replace_selection(widget: Any, text: str) -> None:
    _delete_selection(widget)
    if _is_text(widget):
        widget.insert("insert", text)
    else:
        widget.insert(widget.index("insert"), text)


def _select_all(widget: Any) -> None:
    if _is_text(widget):
        widget.tag_add("sel", "1.0", "end-1c")
        widget.mark_set("insert", "end-1c")
        widget.see("insert")
    else:
        widget.selection_range(0, "end")
        widget.icursor("end")


def _show_context_menu(event: Any) -> str:
    widget = event.widget
    if not _is_editable(widget):
        return "break"
    widget.focus_set()
    menu = tk.Menu(widget, tearoff=False)
    menu.add_command(label="Вирізати", command=lambda: _dispatch(widget, "cut"))
    menu.add_command(label="Копіювати", command=lambda: _dispatch(widget, "copy"))
    menu.add_command(label="Вставити", command=lambda: _dispatch(widget, "paste"))
    menu.add_separator()
    menu.add_command(label="Виділити все", command=lambda: _dispatch(widget, "select_all"))
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()
    return "break"
