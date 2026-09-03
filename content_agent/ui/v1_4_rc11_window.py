from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .v1_4_rc10_window import MainWindow as Rc10MainWindow


class MainWindow(Rc10MainWindow):
    """v1.4.0-rc11: stable, authoritative ordering for the Inbox."""

    VERSION_LABEL = "1.4.0-rc11"

    def __init__(self, root: tk.Tk, database, config) -> None:
        self._rc11_inbox_refresh_serial = 0
        self._rc11_inbox_idle_after_id: str | None = None
        super().__init__(root, database, config)
        self._disable_legacy_inbox_sort_state()
        self._apply_v14_labels()
        self.refresh_groups()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc11")

    def _disable_legacy_inbox_sort_state(self) -> None:
        """Keep exactly one sort engine for Inbox: the v1.3 multi-sort state."""
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return
        state = getattr(self, "_tree_sort_state", None)
        if isinstance(state, dict):
            state.pop(str(tree), None)
        if hasattr(self, "_install_inbox_multisort_headings"):
            self._install_inbox_multisort_headings(tree)

    def _reapply_tree_sort(self, tree: ttk.Treeview) -> None:
        # main_window_enhancements owns generic sorting for other Treeviews.
        # Inbox gained its own multi-sort later, so letting both engines touch
        # the same rows creates lifecycle-dependent ordering after refreshes.
        if tree is getattr(self, "groups_tree", None):
            return
        super()._reapply_tree_sort(tree)

    def _stabilize_inbox_order(self, serial: int) -> None:
        if serial != self._rc11_inbox_refresh_serial or getattr(self, "_closing", False):
            return
        if hasattr(self, "_apply_inbox_sort"):
            self._apply_inbox_sort()

    def _stabilize_inbox_order_idle(self, serial: int) -> None:
        self._rc11_inbox_idle_after_id = None
        self._stabilize_inbox_order(serial)

    def refresh_groups(self) -> None:
        self._rc11_inbox_refresh_serial += 1
        serial = self._rc11_inbox_refresh_serial
        super().refresh_groups()
        self._stabilize_inbox_order(serial)

        # A second pass after Tk has processed pending geometry/redraw work keeps
        # the selected order authoritative even when a background collector or
        # merge completion queued another UI update in the same event-loop turn.
        if not hasattr(self, "root") or getattr(self, "_closing", False):
            return
        if self._rc11_inbox_idle_after_id is not None:
            try:
                self.root.after_cancel(self._rc11_inbox_idle_after_id)
            except tk.TclError:
                pass
        self._rc11_inbox_idle_after_id = self.root.after_idle(
            lambda value=serial: self._stabilize_inbox_order_idle(value)
        )
