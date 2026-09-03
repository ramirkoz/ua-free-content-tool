from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..source_health import ensure_source_health
from .v1_4_rc11_window import MainWindow as Rc11MainWindow


_SOURCE_COLUMNS = ("id", "kind", "name", "health", "yield", "last_new", "errors", "checked", "url")
_SOURCE_WIDTHS = {
    "id": 55,
    "kind": 80,
    "name": 190,
    "health": 220,
    "yield": 65,
    "last_new": 165,
    "errors": 70,
    "checked": 165,
    "url": 400,
}
_SOURCE_LABELS = {
    "uk": {
        "id": "ID",
        "kind": "Тип",
        "name": "Назва",
        "health": "Стан джерела",
        "yield": "Нових",
        "last_new": "Останній новий",
        "errors": "Помилок",
        "checked": "Остання перевірка",
        "url": "Адреса",
    },
    "en": {
        "id": "ID",
        "kind": "Type",
        "name": "Name",
        "health": "Source health",
        "yield": "New",
        "last_new": "Last new item",
        "errors": "Errors",
        "checked": "Last check",
        "url": "Address",
    },
}


class MainWindow(Rc11MainWindow):
    """v1.4.0-rc12: source-health/UI compatibility hotfix."""

    VERSION_LABEL = "1.4.0-rc12"

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc12")

    def _apply_language(self, refresh: bool = True) -> None:
        # Several historical UI layers still update the title while localizing.
        # The current layer must always win after that chain finishes.
        super()._apply_language(refresh=refresh)
        self._apply_v14_labels()
        self._apply_source_health_labels_rc12()

    def _build_sources_tab(self) -> None:
        # RC9 added source editing but rebuilt the Treeview with only five
        # columns. The inherited SourceHealthV13Mixin still refreshes nine
        # diagnostics columns, producing Tk's "Invalid column index health".
        # Build the RC9 controls first, then restore the full source schema before
        # any language/refresh callback can address those columns.
        ensure_source_health(self.db)
        super()._build_sources_tab()
        tree = self.sources_tree
        tree.configure(columns=_SOURCE_COLUMNS, displaycolumns=_SOURCE_COLUMNS)
        for column in _SOURCE_COLUMNS:
            tree.column(column, width=_SOURCE_WIDTHS[column], anchor="w")
        self._apply_source_health_labels_rc12()

    def _apply_source_health_labels_rc12(self) -> None:
        tree = getattr(self, "sources_tree", None)
        if tree is None:
            return
        present = {str(column) for column in tuple(tree.cget("columns"))}
        language = "en" if str(getattr(self.config, "ui_language", "uk") or "uk").casefold().startswith("en") else "uk"
        labels = _SOURCE_LABELS[language]
        for column in _SOURCE_COLUMNS:
            if column in present:
                tree.heading(column, text=labels[column])

    def _apply_source_health_labels(self) -> None:
        # Override the legacy mixin implementation with a defensive version. It
        # is called from inherited localization code during window construction.
        self._apply_source_health_labels_rc12()
