from __future__ import annotations

import tkinter as tk

from .inbox_management_v1_4_rc14 import (
    GroupMembersDialog as Rc14GroupMembersDialog,
    KeywordMergeDialog as Rc14KeywordMergeDialog,
)


_BOTTOM_SAFE_MARGIN = 96
_SIDE_SAFE_MARGIN = 12


def safe_workspace_geometry(screen_width: int, screen_height: int) -> tuple[int, int, int, int]:
    """Return the same near-fullscreen workspace geometry used by large review dialogs.

    A fixed bottom reserve keeps action buttons above the Windows taskbar even on
    DPI-scaled desktops, where Tk's nominal maximized state can extend underneath it.
    """
    width = max(900, int(screen_width) - _SIDE_SAFE_MARGIN)
    height = max(560, int(screen_height) - _BOTTOM_SAFE_MARGIN)
    return width, height, 0, 0


class _FullWorkspaceDialogMixin:
    def _maximize_workspace(self) -> None:
        try:
            self.state("normal")
        except tk.TclError:
            pass
        try:
            width, height, x, y = safe_workspace_geometry(
                int(self.winfo_screenwidth()),
                int(self.winfo_screenheight()),
            )
            self.geometry(f"{width}x{height}+{x}+{y}")
        except tk.TclError:
            self.geometry("1250x720+0+0")


class KeywordMergeDialog(_FullWorkspaceDialogMixin, Rc14KeywordMergeDialog):
    """RC15 keyword result workspace: open near-fullscreen for editorial comparison."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.after_idle(self._maximize_workspace)


class GroupMembersDialog(_FullWorkspaceDialogMixin, Rc14GroupMembersDialog):
    """RC15 merged-block editor: open near-fullscreen for full-text review."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.after_idle(self._maximize_workspace)
