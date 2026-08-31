from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import ttk
from typing import Callable

from ..global_duplicates_v1_3_rc6 import DuplicateCluster
from ..models import NewsGroup
from ..paths import data_dir


DEFAULT_AUTO_SELECT_CONFIDENCE = 90
_LAYOUT_FILE = "duplicate_dialog_layout_v1_4.json"
_DEFAULT_WIDTHS = {
    "#0": 18,
    "use": 80,
    "confidence": 105,
    "cluster": 760,
    "members": 90,
    "reason": 520,
}


def default_cluster_selected(confidence: int) -> bool:
    return int(confidence) >= DEFAULT_AUTO_SELECT_CONFIDENCE


class GlobalDuplicatesDialog(tk.Toplevel):
    """Review merge proposals with safe defaults and persistent working layout."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        clusters: list[DuplicateCluster],
        groups: dict[int, NewsGroup],
        on_apply: Callable[[list[DuplicateCluster]], None],
    ) -> None:
        super().__init__(parent)
        self.clusters = list(clusters)
        self.groups = groups
        self.on_apply = on_apply
        self.selected: set[int] = {
            index for index, cluster in enumerate(self.clusters) if default_cluster_selected(cluster.confidence)
        }
        self._layout_path = data_dir() / _LAYOUT_FILE
        self._layout_save_after_id: str | None = None
        self.title("Дублікати серед усіх нових матеріалів")
        self.minsize(900, 560)
        self.transient(parent.winfo_toplevel())

        header = ttk.Frame(self, padding=(12, 10, 12, 6))
        header.pack(fill="x")
        ttk.Label(
            header,
            text="Знайдено кандидати на об’єднання серед нових матеріалів",
            font="TkHeadingFont",
        ).pack(anchor="w")
        self.summary_var = tk.StringVar()
        ttk.Label(header, textvariable=self.summary_var, foreground="#555").pack(anchor="w", pady=(4, 0))

        columns = ("use", "confidence", "cluster", "members", "reason")
        table = ttk.Frame(self)
        table.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(table, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="")
        self.tree.heading("use", text="Об'єднати")
        self.tree.heading("confidence", text="Впевненість")
        self.tree.heading("cluster", text="Пропозиція")
        self.tree.heading("members", text="Матеріалів")
        self.tree.heading("reason", text="Причина")

        widths = self._load_widths()
        # No Treeview column is allowed to absorb spare window width automatically.
        # With stretch=False, a width dragged by the editor remains exactly that
        # width instead of snapping back when Tk recalculates the maximized layout.
        self.tree.column("#0", width=widths.get("#0", 18), minwidth=16, stretch=False)
        self.tree.column("use", width=widths.get("use", 80), minwidth=70, anchor="center", stretch=False)
        self.tree.column("confidence", width=widths.get("confidence", 105), minwidth=90, anchor="center", stretch=False)
        self.tree.column("cluster", width=widths.get("cluster", 760), minwidth=180, anchor="w", stretch=False)
        self.tree.column("members", width=widths.get("members", 90), minwidth=80, anchor="center", stretch=False)
        self.tree.column("reason", width=widths.get("reason", 520), minwidth=180, anchor="w", stretch=False)

        self.tree_y_scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree_x_scroll = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(
            yscrollcommand=self.tree_y_scroll.set,
            xscrollcommand=self.tree_x_scroll.set,
        )
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree_y_scroll.grid(row=0, column=1, sticky="ns")
        self.tree_x_scroll.grid(row=1, column=0, sticky="ew")

        self.tree.bind("<Button-1>", self._click, add="+")
        self.tree.bind("<space>", self._space)
        self.tree.bind("<ButtonRelease-1>", self._schedule_layout_save, add="+")

        for index, cluster in enumerate(self.clusters):
            titles = [groups[group_id].canonical_title for group_id in cluster.group_ids if group_id in groups]
            parent_id = f"cluster:{index}"
            enabled = index in self.selected
            self.tree.insert(
                "",
                "end",
                iid=parent_id,
                values=(
                    "☑" if enabled else "☐",
                    f"{cluster.confidence}%",
                    " + ".join(titles[:2]),
                    len(cluster.group_ids),
                    cluster.reason,
                ),
                open=True,
                tags=("strong" if cluster.confidence >= DEFAULT_AUTO_SELECT_CONFIDENCE else "possible",),
            )
            for group_id in cluster.group_ids:
                group = groups.get(group_id)
                if group is None:
                    continue
                self.tree.insert(
                    parent_id,
                    "end",
                    iid=f"member:{index}:{group_id}",
                    values=("", "", group.canonical_title, group.source_count, group.last_published_at or "—"),
                )
        self.tree.tag_configure("strong", background="#e5f5e5")
        self.tree.tag_configure("possible", background="#fff5d6")

        actions = ttk.Frame(self, padding=(12, 0, 12, 12))
        actions.pack(fill="x")
        ttk.Button(actions, text="Вибрати всі", command=self.select_all).pack(side="left")
        ttk.Button(actions, text="Зняти всі", command=self.clear_all).pack(side="left", padx=6)
        ttk.Button(actions, text="Закрити", command=self.close).pack(side="right")
        self.apply_button = ttk.Button(actions, text="Об'єднати вибрані матеріали", command=self.apply)
        self.apply_button.pack(side="right", padx=(0, 8))
        self._update_summary()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after_idle(self._maximize)
        self.grab_set()
        self.focus_set()

    def _maximize(self) -> None:
        try:
            self.state("zoomed")
            return
        except tk.TclError:
            pass
        try:
            width = max(900, int(self.winfo_screenwidth()))
            height = max(560, int(self.winfo_screenheight()) - 60)
            self.geometry(f"{width}x{height}+0+0")
        except tk.TclError:
            self.geometry("1250x760")

    def _load_widths(self) -> dict[str, int]:
        result = dict(_DEFAULT_WIDTHS)
        try:
            payload = json.loads(self._layout_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return result
        if not isinstance(payload, dict):
            return result
        widths = payload.get("widths")
        if not isinstance(widths, dict):
            return result
        for key in result:
            try:
                value = int(widths.get(key, result[key]))
            except (TypeError, ValueError):
                continue
            if value >= 16:
                result[key] = value
        return result

    def _schedule_layout_save(self, _event: object | None = None) -> None:
        if self._layout_save_after_id is not None:
            try:
                self.after_cancel(self._layout_save_after_id)
            except tk.TclError:
                pass
        self._layout_save_after_id = self.after(350, self._save_layout)

    def _save_layout(self) -> None:
        self._layout_save_after_id = None
        try:
            widths = {
                key: int(self.tree.column(key, "width"))
                for key in ("#0", "use", "confidence", "cluster", "members", "reason")
            }
            self._layout_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._layout_path.with_name(self._layout_path.name + ".tmp")
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump({"version": 1, "widths": widths}, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._layout_path)
        except (OSError, tk.TclError, TypeError, ValueError):
            return

    def _cluster_index(self, iid: str) -> int | None:
        if not iid.startswith("cluster:"):
            return None
        try:
            return int(iid.split(":", 1)[1])
        except ValueError:
            return None

    def _set(self, index: int, enabled: bool) -> None:
        if enabled:
            self.selected.add(index)
        else:
            self.selected.discard(index)
        iid = f"cluster:{index}"
        values = list(self.tree.item(iid, "values"))
        if values:
            values[0] = "☑" if enabled else "☐"
            self.tree.item(iid, values=values)
        self._update_summary()

    def _click(self, event: tk.Event) -> None:
        iid = self.tree.identify_row(int(event.y))
        column = self.tree.identify_column(int(event.x))
        index = self._cluster_index(iid)
        if index is not None and column == "#1":
            self._set(index, index not in self.selected)

    def _space(self, _event: object | None = None) -> str:
        index = self._cluster_index(self.tree.focus())
        if index is not None:
            self._set(index, index not in self.selected)
        return "break"

    def select_all(self) -> None:
        for index in range(len(self.clusters)):
            self._set(index, True)

    def clear_all(self) -> None:
        for index in range(len(self.clusters)):
            self._set(index, False)

    def _update_summary(self) -> None:
        strong = sum(default_cluster_selected(cluster.confidence) for cluster in self.clusters)
        self.summary_var.set(
            f"Знайдено груп-кандидатів: {len(self.clusters)} · "
            f"автоматично рекомендовано: {strong} · вибрано: {len(self.selected)}"
        )
        self.apply_button.configure(state="normal" if self.selected else "disabled")

    def close(self) -> None:
        self._save_layout()
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def apply(self) -> None:
        chosen = [self.clusters[index] for index in sorted(self.selected)]
        if not chosen:
            return
        self._save_layout()
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        self.on_apply(chosen)
