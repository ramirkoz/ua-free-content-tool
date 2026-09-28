from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .manual_topics_window import ALL_SOURCES, ALL_TOPICS, MainWindow as Rc43MainWindow


class MainWindow(Rc43MainWindow):
    """RC44: keep Inbox source/topic filters on their own visible row."""

    def _install_manual_topic_inbox_filters(self) -> None:
        if hasattr(self, "inbox_source_filter_box"):
            return
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return

        tree_frame = tree.master
        tab = tree_frame.master
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 6), before=tree_frame)
        self._manual_topic_filter_bar = bar

        self.inbox_source_filter_var = tk.StringVar(value=ALL_SOURCES)
        self.inbox_topic_filter_var = tk.StringVar(value=ALL_TOPICS)

        ttk.Label(bar, text="Фільтри:").pack(side="left")
        ttk.Label(bar, text="Джерело:").pack(side="left", padx=(10, 4))
        self.inbox_source_filter_box = ttk.Combobox(
            bar,
            textvariable=self.inbox_source_filter_var,
            state="readonly",
            width=28,
        )
        self.inbox_source_filter_box.pack(side="left", padx=(0, 10))
        self.inbox_source_filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_groups())

        ttk.Label(bar, text="Тема:").pack(side="left", padx=(0, 4))
        self.inbox_topic_filter_box = ttk.Combobox(
            bar,
            textvariable=self.inbox_topic_filter_var,
            state="readonly",
            width=24,
        )
        self.inbox_topic_filter_box.pack(side="left", padx=(0, 10))
        self.inbox_topic_filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_groups())

        ttk.Button(
            bar,
            text="Скинути фільтри",
            command=self.reset_manual_topic_filters,
        ).pack(side="left")

        self._refresh_inbox_filter_choices()


__all__ = ["MainWindow"]
