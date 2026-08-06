from __future__ import annotations

import re
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk
from typing import Any, Iterable

from ..i18n import original_text, tr
from ..scheduling import parse_iso
from .main_window import (
    GROUP_FILTERS,
    GROUP_STATUS_LABELS,
    MainWindow as BaseMainWindow,
)

_ARROW_SUFFIX_RE = re.compile(r"\s+[▲▼]$")
_NUMBER_PREFIX_RE = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)")
_EMPTY_SORT_VALUES = {"", "—", "-", "n/a", "not available"}


def read_public_version(base_dir: Path | None = None) -> str:
    """Read the public version shipped with the source or portable package."""

    if base_dir is not None:
        candidates = [Path(base_dir) / "PUBLIC_VERSION.txt"]
    else:
        candidates = [
            Path(sys.executable).resolve().parent / "PUBLIC_VERSION.txt",
            Path(__file__).resolve().parents[2] / "PUBLIC_VERSION.txt",
            Path.cwd() / "PUBLIC_VERSION.txt",
        ]

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            value = candidate.read_text(encoding="utf-8-sig").strip()
        except OSError:
            continue
        if re.fullmatch(r"\d+(?:\.\d+){1,3}", value):
            return value
    return "unknown"


def history_prediction_label(details: object, language: str = "uk") -> str:
    """Return a compact Inbox label for the saved historical prediction."""

    payload = details if isinstance(details, dict) else {}
    prediction = payload.get("history_prediction")
    if not isinstance(prediction, dict):
        return "—"
    if bool(prediction.get("available")):
        score = max(0, min(100, int(prediction.get("score") or 0)))
        confidence = max(0, min(100, int(prediction.get("confidence") or 0)))
        return f"{score}/100 · {confidence}%"
    return "Insufficient data" if language == "en" else "Недостатньо даних"


def tree_sort_key(value: object) -> tuple[int, object]:
    """Normalize Treeview text into a predictable number/date/text sort key."""

    text = str(value or "").strip()
    if text.casefold() in _EMPTY_SORT_VALUES:
        return 3, ""

    parsed = parse_iso(text)
    if parsed is not None:
        return 1, parsed.timestamp()

    for pattern in ("%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return 1, datetime.strptime(text, pattern).timestamp()
        except ValueError:
            pass

    number = _NUMBER_PREFIX_RE.match(text)
    if number:
        return 0, float(number.group(1).replace(",", "."))
    return 2, text.casefold()


def _walk_treeviews(widget: tk.Misc) -> Iterable[ttk.Treeview]:
    for child in widget.winfo_children():
        if isinstance(child, ttk.Treeview):
            yield child
        yield from _walk_treeviews(child)


class MainWindow(BaseMainWindow):
    """Production UI additions kept separate from the stabilized base window."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._tree_sort_state: dict[str, tuple[str, bool]] = {}
        self._tree_heading_labels: dict[tuple[str, str], str] = {}
        super().__init__(*args, **kwargs)
        self.root.title(f"UA FREE Content Tool — v{read_public_version()}")
        self._install_tree_sorting(reset_labels=True)

    def _inbox_headings(self) -> dict[str, str]:
        if self.config.ui_language == "en":
            return {
                "id": "Block",
                "status": "Status",
                "title": "Event",
                "sources": "Sources",
                "published": "Last mention",
                "score": "Current potential",
                "history": "History forecast",
            }
        return {
            "id": "Блок",
            "status": "Статус",
            "title": "Подія",
            "sources": "Джерел",
            "published": "Остання згадка",
            "score": "Поточний потенціал",
            "history": "Прогноз за історією",
        }

    def _refresh_inbox_headings(self) -> None:
        if not hasattr(self, "groups_tree"):
            return
        for column, label in self._inbox_headings().items():
            self.groups_tree.heading(column, text=label)

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        self._refresh_inbox_headings()
        if hasattr(self, "_tree_heading_labels"):
            self._install_tree_sorting(reset_labels=True)

    def _build_inbox_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Вхідні")

        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=(0, 6))
        self.group_filter = tk.StringVar(value="Активні")
        ttk.Label(actions, text="Показати").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.group_filter_box = ttk.Combobox(
            actions,
            textvariable=self.group_filter,
            values=tuple(GROUP_FILTERS),
            state="readonly",
            width=13,
        )
        self.group_filter_box.grid(row=0, column=1, sticky="w", padx=(0, 5))
        self.group_filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_groups())
        ttk.Button(actions, text="Оновити", command=self.refresh_groups).grid(row=0, column=2, padx=3)
        ttk.Button(actions, text="Відновити / прийняти", command=self.accept_selected_group).grid(
            row=0, column=3, padx=3
        )
        ttk.Button(actions, text="Видалити", command=self.delete_selected_groups).grid(row=0, column=4, padx=3)
        tk.Button(
            actions,
            text="Запам’ятати й більше не пропонувати",
            command=self.remember_and_exclude_selected_groups,
            bg="#b3261e",
            fg="white",
            activebackground="#8f1f19",
            activeforeground="white",
            relief="flat",
            padx=9,
            pady=4,
        ).grid(row=0, column=5, padx=3)
        ttk.Button(
            actions,
            text="Пошук схожих за темою матеріалів",
            command=self.find_all_by_topic,
        ).grid(row=0, column=6, padx=3)
        tk.Button(
            actions,
            text="Об’єднати в один блок",
            command=self.merge_selected_groups,
            bg="#2e7d32",
            fg="white",
            activebackground="#256628",
            activeforeground="white",
            relief="flat",
            padx=9,
            pady=4,
        ).grid(row=0, column=7, padx=3)
        actions.columnconfigure(8, weight=1)

        self.topic_search_status_var = tk.StringVar(
            value="Оберіть одну новину й натисніть «Пошук схожих за темою матеріалів»."
        )
        ttk.Label(
            tab,
            textvariable=self.topic_search_status_var,
            foreground="#555",
            wraplength=1350,
        ).pack(fill="x", pady=(0, 4))
        ttk.Label(
            tab,
            text="Вибір: Shift — діапазон, Ctrl — окремі блоки, Ctrl+A — усі видимі, Delete — просте видалення.",
        ).pack(fill="x", pady=(0, 6))

        tree_frame = ttk.Frame(tab)
        tree_frame.pack(fill="both", expand=True)
        columns = ("id", "status", "title", "sources", "published", "score", "history")
        self.groups_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
        )
        widths = {
            "id": 70,
            "status": 100,
            "title": 560,
            "sources": 85,
            "published": 190,
            "score": 145,
            "history": 180,
        }
        for column, label in self._inbox_headings().items():
            self.groups_tree.heading(column, text=label)
            self.groups_tree.column(column, width=widths[column], anchor="w")
        self.groups_tree.tag_configure("approved", background="#e7f5e8")
        self.groups_tree.tag_configure("topic_strong", background="#dff2df")
        self.groups_tree.tag_configure("topic_possible", background="#fff4cc")
        groups_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.groups_tree.yview)
        self.groups_tree.configure(yscrollcommand=groups_scroll.set)
        self.groups_tree.pack(side="left", fill="both", expand=True)
        groups_scroll.pack(side="right", fill="y")
        self.groups_tree.bind("<Button-1>", self._remember_group_selection_anchor, add="+")
        self.groups_tree.bind("<Shift-Button-1>", self._select_group_range)
        self.groups_tree.bind("<Double-1>", lambda _event: self.accept_selected_group())
        self.groups_tree.bind("<Control-a>", self._select_all_group_rows)
        self.groups_tree.bind("<Control-A>", self._select_all_group_rows)
        self.groups_tree.bind("<Delete>", self._delete_selected_group_rows)
        self.groups_tree.bind("<Prior>", self._page_group_tree)
        self.groups_tree.bind("<Next>", self._page_group_tree)
        self.groups_tree.bind("<Home>", self._page_group_tree)
        self.groups_tree.bind("<End>", self._page_group_tree)

    def refresh_groups(self) -> None:
        selected_before = tuple(self.groups_tree.selection())
        focus_before = self.groups_tree.focus()
        yview_before = self.groups_tree.yview()
        self.groups_tree.delete(*self.groups_tree.get_children())
        selected_filter = original_text(self.group_filter.get())
        status = GROUP_FILTERS.get(selected_filter)
        for group in self.db.list_groups(status=status):
            current_score = (
                f"{group.explosiveness_score}/100"
                if group.explosiveness_score or group.explosiveness_details
                else "—"
            )
            historical_score = history_prediction_label(
                group.explosiveness_details,
                self.config.ui_language,
            )
            tags = ("approved",) if group.status == "approved" else ()
            self.groups_tree.insert(
                "",
                "end",
                iid=str(group.id),
                values=(
                    group.id,
                    tr(GROUP_STATUS_LABELS.get(group.status, group.status), self.config.ui_language),
                    group.canonical_title,
                    group.source_count,
                    group.last_published_at or "—",
                    current_score,
                    historical_score,
                ),
                tags=tags,
            )
        existing = [iid for iid in selected_before if self.groups_tree.exists(iid)]
        if existing:
            self.groups_tree.selection_set(existing)
        if focus_before and self.groups_tree.exists(focus_before):
            self.groups_tree.focus(focus_before)
        if yview_before:
            self.groups_tree.yview_moveto(float(yview_before[0]))
        self._reapply_tree_sort(self.groups_tree)

    def _install_tree_sorting(self, *, reset_labels: bool = False) -> None:
        if not hasattr(self, "root"):
            return
        for tree in _walk_treeviews(self.root):
            tree_id = str(tree)
            for column in tuple(tree.cget("columns")):
                column_name = str(column)
                current = _ARROW_SUFFIX_RE.sub("", str(tree.heading(column_name, "text")))
                key = (tree_id, column_name)
                if reset_labels or key not in self._tree_heading_labels:
                    self._tree_heading_labels[key] = current
                tree.heading(
                    column_name,
                    text=self._tree_heading_labels[key],
                    command=lambda target=tree, name=column_name: self._sort_tree(target, name),
                )
            self._update_tree_heading_arrows(tree)

    def _sort_tree(self, tree: ttk.Treeview, column: str) -> None:
        previous = self._tree_sort_state.get(str(tree))
        descending = not previous[1] if previous and previous[0] == column else False
        self._apply_tree_sort(tree, column, descending)

    def _apply_tree_sort(self, tree: ttk.Treeview, column: str, descending: bool) -> None:
        rows = list(tree.get_children(""))
        sortable: list[tuple[tuple[int, object], int, str]] = []
        empty: list[str] = []
        for index, item_id in enumerate(rows):
            key = tree_sort_key(tree.set(item_id, column))
            if key[0] == 3:
                empty.append(item_id)
            else:
                sortable.append((key, index, item_id))
        sortable.sort(key=lambda row: (row[0], row[1]), reverse=descending)
        ordered = [item_id for _key, _index, item_id in sortable] + empty
        for position, item_id in enumerate(ordered):
            tree.move(item_id, "", position)
        self._tree_sort_state[str(tree)] = (column, descending)
        self._update_tree_heading_arrows(tree)

    def _update_tree_heading_arrows(self, tree: ttk.Treeview) -> None:
        state = self._tree_sort_state.get(str(tree))
        for column in tuple(tree.cget("columns")):
            column_name = str(column)
            base = self._tree_heading_labels.get(
                (str(tree), column_name),
                _ARROW_SUFFIX_RE.sub("", str(tree.heading(column_name, "text"))),
            )
            suffix = ""
            if state and state[0] == column_name:
                suffix = " ▼" if state[1] else " ▲"
            tree.heading(column_name, text=base + suffix)

    def _reapply_tree_sort(self, tree: ttk.Treeview) -> None:
        state = self._tree_sort_state.get(str(tree))
        if state:
            self._apply_tree_sort(tree, state[0], state[1])

    def refresh_sources(self) -> None:
        super().refresh_sources()
        self._reapply_tree_sort(self.sources_tree)

    def refresh_queue(self) -> None:
        super().refresh_queue()
        self._reapply_tree_sort(self.queue_tree)

    def refresh_history(self) -> None:
        super().refresh_history()
        if hasattr(self, "history_tree"):
            self._reapply_tree_sort(self.history_tree)
