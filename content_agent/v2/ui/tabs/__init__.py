from __future__ import annotations

import tkinter as tk

from ..legacy_manual_topics_window_rc44 import MainWindow as _LegacyStableMainWindow
from .base import TabController
from .inbox import InboxFilterState, InboxTabController


def _rc58_rename_system_tab(self) -> None:
    """RC58 launch hotfix: restore the RC57 system-tab rename hook lost in branch composition."""
    notebook = getattr(self, "notebook", None)
    if notebook is None:
        return
    for tab_id in notebook.tabs():
        try:
            text = str(notebook.tab(tab_id, "text") or "")
        except tk.TclError:
            continue
        if "supervisor" in text.casefold() or "наглядач" in text.casefold():
            notebook.tab(tab_id, text="Стан системи")


def _rc58_apply_publication_layout(self) -> None:
    """RC58 launch hotfix: restore the RC57 publication-layout hook lost in branch composition."""
    canvas = getattr(self, "targets_canvas", None)
    if canvas is not None:
        try:
            canvas.configure(height=190)
        except tk.TclError:
            pass
    media_tree = getattr(self, "media_candidates_tree", None)
    if media_tree is not None:
        try:
            media_tree.configure(height=2)
        except tk.TclError:
            pass


if not hasattr(_LegacyStableMainWindow, "_rename_system_tab"):
    _LegacyStableMainWindow._rename_system_tab = _rc58_rename_system_tab
if not hasattr(_LegacyStableMainWindow, "_apply_rc54_publication_layout"):
    _LegacyStableMainWindow._apply_rc54_publication_layout = _rc58_apply_publication_layout


__all__ = ["InboxFilterState", "InboxTabController", "TabController"]
