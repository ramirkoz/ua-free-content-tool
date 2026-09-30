from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable


class StatusBar(ttk.Frame):
    """Single bottom status surface shared by V2 tabs."""

    def __init__(self, master, *, operation_var: tk.StringVar, status_var: tk.StringVar):
        super().__init__(master, padding=(10, 4))
        ttk.Label(self, textvariable=operation_var).pack(side="left")
        ttk.Separator(self, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Label(self, textvariable=status_var, anchor="w").pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(self, mode="indeterminate", length=130)
        self.progress.pack(side="right", padx=(8, 0))


class ActionBar(ttk.Frame):
    """Compact action row with one visually primary operation."""

    def add(self, text: str, command: Callable[[], object], *, primary: bool = False) -> ttk.Button:
        button = ttk.Button(self, text=text, command=command)
        button.pack(side="left" if primary else "right", padx=(0, 6) if primary else (6, 0))
        return button


class FilterBar(ttk.Frame):
    """Reusable Source + Topic + Search filter surface."""

    def __init__(
        self,
        master,
        *,
        source_var: tk.StringVar,
        topic_var: tk.StringVar,
        search_var: tk.StringVar | None = None,
        on_change: Callable[[], object] | None = None,
        on_reset: Callable[[], object] | None = None,
    ) -> None:
        super().__init__(master)
        self.source_box = ttk.Combobox(self, textvariable=source_var, state="readonly", width=24)
        self.topic_box = ttk.Combobox(self, textvariable=topic_var, state="readonly", width=20)
        ttk.Label(self, text="Джерело:").pack(side="left", padx=(0, 4))
        self.source_box.pack(side="left", padx=(0, 8))
        ttk.Label(self, text="Тема:").pack(side="left", padx=(0, 4))
        self.topic_box.pack(side="left", padx=(0, 8))
        if search_var is not None:
            ttk.Label(self, text="Пошук:").pack(side="left", padx=(0, 4))
            self.search_entry = ttk.Entry(self, textvariable=search_var, width=28)
            self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        else:
            self.search_entry = None
        if on_reset is not None:
            ttk.Button(self, text="Скинути", command=on_reset).pack(side="right")
        if on_change is not None:
            self.source_box.bind("<<ComboboxSelected>>", lambda _event: on_change())
            self.topic_box.bind("<<ComboboxSelected>>", lambda _event: on_change())
            if self.search_entry is not None:
                self.search_entry.bind("<Return>", lambda _event: on_change())


class PublicationStatus:
    """Canonical operator-facing labels for publication outcomes."""

    LABELS = {
        "not_attempted": "Не надсилалось",
        "sent": "Опубліковано",
        "failed_known": "Помилка",
        "unknown": "Невідомо — перевірте платформу",
        "confirmed_not_sent": "Підтверджено: поста немає",
    }

    @classmethod
    def label(cls, outcome: object) -> str:
        value = str(getattr(outcome, "value", outcome) or "").strip()
        return cls.LABELS.get(value, value or "—")


__all__ = ["ActionBar", "FilterBar", "PublicationStatus", "StatusBar"]
