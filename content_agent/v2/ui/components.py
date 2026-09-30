from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk


class ActionBar(ttk.Frame):
    """Small reusable action row with consistent spacing."""

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._left = ttk.Frame(self)
        self._right = ttk.Frame(self)
        self._left.pack(side="left", fill="x", expand=True)
        self._right.pack(side="right")

    def add_action(
        self,
        text: str,
        command: Callable[[], object],
        *,
        primary: bool = False,
        right: bool = False,
    ) -> ttk.Button:
        parent = self._right if right else self._left
        button = ttk.Button(parent, text=text, command=command)
        button.pack(side="left", padx=(0, 6) if not right else (6, 0))
        if primary:
            try:
                button.configure(default="active")
            except tk.TclError:
                pass
        return button


class FilterBar(ActionBar):
    """Authoritative Inbox Source + Topic + Search controls."""

    def __init__(
        self,
        master,
        *,
        source_var: tk.StringVar,
        topic_var: tk.StringVar,
        search_var: tk.StringVar,
        on_change: Callable[[], object],
        on_reset: Callable[[], object],
        all_sources: str,
        all_topics: str,
    ) -> None:
        super().__init__(master)
        self.source_var = source_var
        self.topic_var = topic_var
        self.search_var = search_var
        self.on_change = on_change
        self._debounce_id: str | None = None

        ttk.Label(self._left, text="Джерело:").pack(side="left", padx=(0, 4))
        self.source_box = ttk.Combobox(
            self._left,
            textvariable=source_var,
            values=(all_sources,),
            state="readonly",
            width=25,
        )
        self.source_box.pack(side="left", padx=(0, 8))
        self.source_box.bind("<<ComboboxSelected>>", lambda _event: self.on_change())

        ttk.Label(self._left, text="Тема:").pack(side="left", padx=(0, 4))
        self.topic_box = ttk.Combobox(
            self._left,
            textvariable=topic_var,
            values=(all_topics,),
            state="readonly",
            width=21,
        )
        self.topic_box.pack(side="left", padx=(0, 8))
        self.topic_box.bind("<<ComboboxSelected>>", lambda _event: self.on_change())

        ttk.Label(self._left, text="Пошук:").pack(side="left", padx=(0, 4))
        self.search_entry = ttk.Entry(self._left, textvariable=search_var, width=28)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.search_entry.bind("<Return>", lambda _event: self.on_change())
        self.search_entry.bind("<KeyRelease>", self._debounced_change)
        self.reset_button = self.add_action("Скинути", on_reset, right=True)

    def _debounced_change(self, _event=None) -> None:
        if self._debounce_id is not None:
            try:
                self.after_cancel(self._debounce_id)
            except tk.TclError:
                pass
        self._debounce_id = self.after(250, self._run_debounced_change)

    def _run_debounced_change(self) -> None:
        self._debounce_id = None
        self.on_change()

    def set_choices(self, *, sources: tuple[str, ...], topics: tuple[str, ...]) -> None:
        self.source_box.configure(values=sources)
        self.topic_box.configure(values=topics)

    def focus_search(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, "end")


class StatusBar(ttk.Frame):
    """Shared bottom status/progress bar."""

    def __init__(self, master, *, operation_var: tk.StringVar, status_var: tk.StringVar) -> None:
        super().__init__(master, padding=(10, 4))
        ttk.Label(self, textvariable=operation_var).pack(side="left")
        ttk.Separator(self, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Label(self, textvariable=status_var, anchor="w").pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(self, mode="indeterminate", length=130)
        self.progress.pack(side="right", padx=(8, 0))


class PublicationStatus(ttk.Frame):
    """Shared explicit publication-state control for UNKNOWN outcomes."""

    def __init__(
        self,
        master,
        *,
        status_var: tk.StringVar,
        on_exists: Callable[[], object],
        on_absent: Callable[[], object],
    ) -> None:
        super().__init__(master)
        self.label = ttk.Label(self, textvariable=status_var)
        self.label.pack(side="left", padx=(6, 4))
        self.exists_button = ttk.Button(self, text="Пост є", command=on_exists, state="disabled")
        self.exists_button.pack(side="left", padx=(4, 2))
        self.absent_button = ttk.Button(self, text="Поста немає", command=on_absent, state="disabled")
        self.absent_button.pack(side="left", padx=2)

    def set_unknown(self, active: bool) -> None:
        state = "normal" if active else "disabled"
        self.exists_button.configure(state=state)
        self.absent_button.configure(state=state)


__all__ = ["ActionBar", "FilterBar", "PublicationStatus", "StatusBar"]
