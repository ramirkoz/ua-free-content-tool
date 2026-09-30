from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .components import FilterBar, PublicationStatus, StatusBar
from .legacy_manual_topics_window_rc44 import MainWindow as LegacyStableMainWindow
from .manual_topics_window import ALL_SOURCES, ALL_TOPICS
from .tabs.inbox import InboxTabController


class MainWindow(LegacyStableMainWindow):
    """Canonical V2 shell with the first extracted tab controller.

    RC53 keeps the proven legacy shell as one frozen compatibility boundary while
    Inbox state/query/rendering moves to composition. New RC-specific window layers
    are forbidden; future UI work extends controllers/components instead.
    """

    ALL_SOURCES_LABEL = ALL_SOURCES
    ALL_TOPICS_LABEL = ALL_TOPICS

    def __init__(self, root, database_or_services, config=None) -> None:
        self._inbox_controller: InboxTabController | None = None
        super().__init__(root, database_or_services, config)
        self._inbox_controller = InboxTabController(self, self._rc53_filter_bar)
        self._inbox_controller.refresh_choices()
        self._rename_system_tab()
        self.refresh_groups()

    # ------------------------------------------------------------------
    # Shared FilterBar. Dynamic dispatch makes this replace the RC43/RC44
    # source/topic bar during construction, so no duplicate legacy filter renders.
    # ------------------------------------------------------------------
    def _install_manual_topic_inbox_filters(self) -> None:
        if hasattr(self, "_rc53_filter_bar"):
            return
        tree = getattr(self, "groups_tree", None)
        if tree is None:
            return
        tree_frame = tree.master
        tab = tree_frame.master
        self.inbox_source_filter_var = tk.StringVar(master=self.root, value=ALL_SOURCES)
        self.inbox_topic_filter_var = tk.StringVar(master=self.root, value=ALL_TOPICS)
        self.inbox_search_var = tk.StringVar(master=self.root, value="")
        bar = FilterBar(
            tab,
            source_var=self.inbox_source_filter_var,
            topic_var=self.inbox_topic_filter_var,
            search_var=self.inbox_search_var,
            on_change=self.refresh_groups,
            on_reset=self.reset_manual_topic_filters,
            all_sources=ALL_SOURCES,
            all_topics=ALL_TOPICS,
        )
        bar.pack(fill="x", pady=(0, 6), before=tree_frame)
        self._manual_topic_filter_bar = bar
        self._rc53_filter_bar = bar
        self.inbox_source_filter_box = bar.source_box
        self.inbox_topic_filter_box = bar.topic_box
        # RC14 keyword entry served a separate historical Inbox-search surface.
        # RC53 owns search in the single FilterBar, so hide the duplicate if present.
        old_search = getattr(self, "_rc14_keyword_entry", None)
        if old_search is not None:
            try:
                old_search.grid_remove()
            except tk.TclError:
                try:
                    old_search.pack_forget()
                except tk.TclError:
                    pass
        self._refresh_inbox_filter_choices()

    def _refresh_inbox_filter_choices(self) -> None:
        controller = getattr(self, "_inbox_controller", None)
        if controller is not None:
            controller.refresh_choices()
            return
        if not hasattr(self, "inbox_source_filter_box"):
            return
        source_rows = self.db.source_topic_rows()
        source_labels: list[str] = []
        source_map: dict[str, int] = {}
        for row in source_rows:
            label = f"{str(row['name'])} [#{int(row['id'])}]"
            source_labels.append(label)
            source_map[label] = int(row["id"])
        topic_rows = self.db.list_manual_topics()
        topic_labels = [str(row["name"]) for row in topic_rows]
        topic_map = {str(row["name"]): int(row["id"]) for row in topic_rows}
        self._inbox_source_label_to_id = source_map
        self._inbox_topic_label_to_id = topic_map
        self._rc53_filter_bar.set_choices(
            sources=(ALL_SOURCES, *source_labels),
            topics=(ALL_TOPICS, *topic_labels),
        )

    def reset_manual_topic_filters(self) -> None:
        controller = getattr(self, "_inbox_controller", None)
        if controller is not None:
            controller.reset()
            return
        self.inbox_source_filter_var.set(ALL_SOURCES)
        self.inbox_topic_filter_var.set(ALL_TOPICS)
        if hasattr(self, "inbox_search_var"):
            self.inbox_search_var.set("")
        self.refresh_groups()

    def _active_inbox_source_id(self) -> int | None:
        return getattr(self, "_inbox_source_label_to_id", {}).get(
            str(getattr(self, "inbox_source_filter_var", tk.StringVar(master=self.root)).get() or "")
        )

    def _active_inbox_topic_id(self) -> int | None:
        return getattr(self, "_inbox_topic_label_to_id", {}).get(
            str(getattr(self, "inbox_topic_filter_var", tk.StringVar(master=self.root)).get() or "")
        )

    def refresh_groups(self) -> None:
        controller = getattr(self, "_inbox_controller", None)
        if controller is None:
            # Construction compatibility only. Once MainWindow.__init__ completes,
            # all operator refreshes go through SQL-backed InboxTabController.
            return super().refresh_groups()
        controller.refresh()

    # ------------------------------------------------------------------
    # Shared StatusBar replacing the RC48 inline implementation.
    # ------------------------------------------------------------------
    def _apply_rc48_shell_layout(self) -> None:
        super()._apply_rc48_shell_layout()
        old = getattr(self, "_rc48_status_bar", None)
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:
                pass
        bar = StatusBar(self.root, operation_var=self.operation_var, status_var=self.status_var)
        bar.pack(side="bottom", fill="x")
        self._rc48_status_bar = bar
        self.operation_progress = bar.progress

    # ------------------------------------------------------------------
    # Shared PublicationStatus while preserving RC48 compatibility attributes.
    # ------------------------------------------------------------------
    def _install_rc48_history_unknown_controls(self) -> None:
        retry = getattr(self, "history_retry_button", None)
        parent = getattr(retry, "master", None)
        if parent is None or hasattr(self, "_rc48_unknown_status_var"):
            return
        try:
            retry.configure(text="Повторити")
        except Exception:
            pass
        self._rc48_unknown_status_var = tk.StringVar(master=self.root, value="")
        status = PublicationStatus(
            parent,
            status_var=self._rc48_unknown_status_var,
            on_exists=self._rc48_confirm_unknown_sent,
            on_absent=self._rc48_confirm_unknown_not_sent,
        )
        status.pack(side="left", padx=(6, 0))
        self._rc53_publication_status = status
        self._rc48_unknown_label = status.label
        self._rc48_post_exists_button = status.exists_button
        self._rc48_post_absent_button = status.absent_button
        overview = getattr(self, "history_overview_tree", None)
        detail = getattr(self, "history_detail_tree", None)
        if overview is not None:
            overview.bind("<<TreeviewSelect>>", lambda _event: self._update_rc48_history_unknown_state(), add="+")
        if detail is not None:
            detail.bind("<<TreeviewSelect>>", lambda _event: self._update_rc48_history_unknown_state(), add="+")
        self._update_rc48_history_unknown_state()

    def _rc48_focus_inbox_search(self, _event=None):
        controller = getattr(self, "_inbox_controller", None)
        if controller is not None:
            controller.focus_primary()
            return "break"
        bar = getattr(self, "_rc53_filter_bar", None)
        if bar is not None:
            bar.focus_search()
            return "break"
        return None

    def _rc48_escape_inbox_search(self, _event=None):
        controller = getattr(self, "_inbox_controller", None)
        if controller is not None:
            return controller.escape()
        if hasattr(self, "inbox_search_var") and str(self.inbox_search_var.get() or ""):
            self.inbox_search_var.set("")
            self.refresh_groups()
            return "break"
        return None

    def _rename_system_tab(self) -> None:
        notebook = getattr(self, "notebook", None)
        if notebook is None:
            return
        for tab_id in notebook.tabs():
            try:
                text = str(notebook.tab(tab_id, "text") or "")
            except tk.TclError:
                continue
            if "supervisor" in text.casefold() or "наглядач" in text.casefold():
                notebook.tab(tab_id, text="Стан системи")


__all__ = ["MainWindow"]
