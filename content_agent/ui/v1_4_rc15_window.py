from __future__ import annotations

from collections.abc import Mapping, Sequence
import tkinter as tk
from tkinter import ttk

from . import v1_4_rc14_window as rc14_window_module
from .inbox_management_v1_4_rc15 import GroupMembersDialog, KeywordMergeDialog
from .v1_4_rc14_window import MainWindow as Rc14MainWindow


# Inherited RC14 methods resolve these dialog classes from their defining module.
# Swap only the dialog implementations, leaving RC14 merge/detach behavior intact.
rc14_window_module.KeywordMergeDialog = KeywordMergeDialog
rc14_window_module.GroupMembersDialog = GroupMembersDialog

ALL_SOURCES_LABEL = "Усі джерела"


def visible_group_ids_for_source(
    group_ids: Sequence[int],
    source_names_by_group: Mapping[int, Sequence[str]],
    selected_source: str,
) -> list[int]:
    """Filter visible Inbox groups by source; merged groups match any member source."""
    selected = str(selected_source or "").strip()
    if not selected or selected == ALL_SOURCES_LABEL:
        return [int(group_id) for group_id in group_ids]
    return [
        int(group_id)
        for group_id in group_ids
        if selected in tuple(source_names_by_group.get(int(group_id), ()))
    ]


class MainWindow(Rc14MainWindow):
    """v1.4.0-rc15: full Inbox review workspaces and source filtering."""

    VERSION_LABEL = "1.4.0-rc15"

    def __init__(self, root: tk.Tk, database, config) -> None:
        self._rc15_source_filter_box: ttk.Combobox | None = None
        self.inbox_source_filter_var = tk.StringVar(master=root, value=ALL_SOURCES_LABEL)
        super().__init__(root, database, config)
        self._apply_v14_labels()
        self.refresh_groups()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc15")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        self._apply_v14_labels()

    def _install_rc14_inbox_tools(self) -> None:
        super()._install_rc14_inbox_tools()
        if self._rc15_source_filter_box is not None:
            return
        bar = getattr(self, "_rc14_inbox_tools_frame", None)
        if bar is None:
            return

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=(10, 8))
        ttk.Label(bar, text="Джерело:").pack(side="left")
        combo = ttk.Combobox(
            bar,
            textvariable=self.inbox_source_filter_var,
            values=(ALL_SOURCES_LABEL,),
            state="readonly",
            width=28,
        )
        combo.pack(side="left", padx=(6, 0))
        combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_groups())
        self._rc15_source_filter_box = combo

    def refresh_groups(self) -> None:
        super().refresh_groups()
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return

        raw_iids = tuple(tree.get_children(""))
        if not raw_iids:
            if self._rc15_source_filter_box is not None:
                self._rc15_source_filter_box.configure(values=(ALL_SOURCES_LABEL,))
            if self.inbox_source_filter_var.get() != ALL_SOURCES_LABEL:
                self.inbox_source_filter_var.set(ALL_SOURCES_LABEL)
            return

        group_ids = [int(iid) for iid in raw_iids]
        try:
            source_names_by_group = self.db.source_names_for_group_ids(group_ids)
        except Exception:
            # Inbox must remain usable even if the optional filter lookup fails.
            source_names_by_group = {}

        available_sources = sorted(
            {
                source_name
                for names in source_names_by_group.values()
                for source_name in names
                if str(source_name or "").strip()
            },
            key=str.casefold,
        )
        values = (ALL_SOURCES_LABEL, *available_sources)
        if self._rc15_source_filter_box is not None:
            self._rc15_source_filter_box.configure(values=values)

        selected_source = str(self.inbox_source_filter_var.get() or ALL_SOURCES_LABEL).strip()
        if selected_source not in values:
            selected_source = ALL_SOURCES_LABEL
            self.inbox_source_filter_var.set(selected_source)

        visible_ids = set(visible_group_ids_for_source(group_ids, source_names_by_group, selected_source))
        if len(visible_ids) == len(group_ids):
            return
        for iid in raw_iids:
            if int(iid) not in visible_ids:
                tree.delete(iid)
