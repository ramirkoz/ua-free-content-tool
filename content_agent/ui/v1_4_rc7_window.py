from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..destinations_v1_4 import destination_ready, normalize_legacy_target_keys
from ..target_presets_v1_2_1 import LAST_SELECTION_LABEL, matching_preset_name
from . import ai_workflow_v1_3_rc6
from .global_duplicates_dialog_v1_3_rc6 import GlobalDuplicatesDialog as BaseGlobalDuplicatesDialog
from .v1_4_rc6_window import MainWindow as Rc6MainWindow


_BOTTOM_SAFE_MARGIN = 96
_SIDE_SAFE_MARGIN = 12


def safe_dialog_geometry(screen_width: int, screen_height: int) -> tuple[int, int, int, int]:
    """Return a near-fullscreen geometry that stays above the Windows taskbar.

    RC6 used ``state('zoomed')``. On the user's Windows desktop that maximized the
    transient dialog under the taskbar, so the action footer was physically outside
    the usable area even though the grid itself was correct. Tk geometry values and
    ``winfo_screen*`` use the same coordinate space, so a small explicit reserve is
    more reliable across DPI scaling than mixing Win32 physical pixels into Tk.
    """

    width = max(900, int(screen_width) - _SIDE_SAFE_MARGIN)
    height = max(560, int(screen_height) - _BOTTOM_SAFE_MARGIN)
    return width, height, 0, 0


class Rc7GlobalDuplicatesDialog(BaseGlobalDuplicatesDialog):
    """RC7 duplicate review: large window, but never underneath the taskbar."""

    def _maximize(self) -> None:
        try:
            self.state("normal")
        except tk.TclError:
            pass
        try:
            width, height, x, y = safe_dialog_geometry(
                int(self.winfo_screenwidth()),
                int(self.winfo_screenheight()),
            )
            self.geometry(f"{width}x{height}+{x}+{y}")
            self.after(120, self._ensure_action_footer_visible)
        except tk.TclError:
            self.geometry("1250x720+0+0")

    def _ensure_action_footer_visible(self) -> None:
        """Runtime guard: shrink once if the actual footer still overlaps taskbar."""

        try:
            self.update_idletasks()
            apply_button = self._find_action_button(self)
            if apply_button is None:
                return
            button_bottom = int(apply_button.winfo_rooty()) + int(apply_button.winfo_height())
            safe_bottom = int(self.winfo_screenheight()) - 56
            if button_bottom <= safe_bottom:
                return
            overflow = button_bottom - safe_bottom + 18
            new_height = max(560, int(self.winfo_height()) - overflow)
            self.geometry(
                f"{int(self.winfo_width())}x{new_height}+{int(self.winfo_x())}+{int(self.winfo_y())}"
            )
        except tk.TclError:
            return

    @classmethod
    def _find_action_button(cls, widget: tk.Misc) -> ttk.Button | None:
        for child in widget.winfo_children():
            if isinstance(child, ttk.Button):
                try:
                    if "Об'єднати вибрані" in str(child.cget("text")):
                        return child
                except tk.TclError:
                    pass
            found = cls._find_action_button(child)
            if found is not None:
                return found
        return None


# The historical AI workflow imported the dialog class directly. Replace that
# module reference once, at RC7 import time, so the real runtime path uses the
# corrected dialog without duplicating the whole duplicate-search workflow.
ai_workflow_v1_3_rc6.GlobalDuplicatesDialog = Rc7GlobalDuplicatesDialog


class MainWindow(Rc6MainWindow):
    """v1.4.0-rc7: real work-area dialog + authoritative last-used targets."""

    VERSION_LABEL = "1.4.0-rc7"

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc7")

    def apply_recommendations(self, recommendations: list[str]) -> None:
        """For every fresh material, restore the last actually used destinations.

        The old preset layer already had this behaviour, but v1.4 overrode
        ``apply_recommendations`` and silently replaced it with destination
        recommendations. RC4 only restored ``last_targets`` once during startup,
        so every subsequently opened fresh story could switch to all/recommended
        profiles again. RC7 makes the persisted last-used selection authoritative
        on every fresh material load.
        """

        state = getattr(self, "_target_preset_state", None)
        last = list(getattr(state, "last_targets", []) or []) if state is not None else []
        normalized = normalize_legacy_target_keys(self.config, last)
        usable = [
            key
            for key in normalized
            if key in getattr(self, "target_vars", {}) and destination_ready(self.config, key)
        ]
        if usable:
            self._apply_target_keys(usable)
            if hasattr(self, "_refresh_target_preset_controls"):
                preferred = matching_preset_name(self._target_preset_state, usable) or LAST_SELECTION_LABEL
                self._refresh_target_preset_controls(preferred)
            return
        super().apply_recommendations(recommendations)
