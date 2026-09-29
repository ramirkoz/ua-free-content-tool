from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class StatusBar(ttk.Frame):
    """Compact always-visible operation/status surface."""

    def __init__(self, master, *, operation_var, status_var) -> None:
        super().__init__(master, padding=(10, 4))
        ttk.Label(self, textvariable=operation_var).pack(side="left")
        ttk.Separator(self, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Label(self, textvariable=status_var, anchor="w").pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(self, mode="indeterminate", length=130)
        self.progress.pack(side="right", padx=(8, 0))


class ActionBar(ttk.Frame):
    """Shared compact action container for operator-heavy tabs."""


class FilterBar(ttk.Frame):
    """Shared compact filter container. Concrete filters remain controller-owned."""


class PublicationStatus(ttk.Frame):
    """Shared presentation boundary for per-destination publication states."""

    def __init__(self, master) -> None:
        super().__init__(master)
        self.value = tk.StringVar(master=master, value="")
        ttk.Label(self, textvariable=self.value, anchor="w").pack(fill="x")
