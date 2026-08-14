from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ..global_duplicates_v1_3_rc6 import DuplicateCluster
from ..models import NewsGroup


class GlobalDuplicatesDialog(tk.Toplevel):
    """Review several independent merge proposals from one global Codex pass."""

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
        self.selected: set[int] = set(range(len(self.clusters)))
        self.title("Дублікати серед усіх нових матеріалів")
        self.geometry("1250x760")
        self.minsize(900, 560)
        self.transient(parent.winfo_toplevel())

        header = ttk.Frame(self, padding=(12, 10, 12, 6))
        header.pack(fill="x")
        ttk.Label(
            header,
            text="Codex проаналізував усі нові блоки між собою",
            font="TkHeadingFont",
        ).pack(anchor="w")
        self.summary_var = tk.StringVar()
        ttk.Label(header, textvariable=self.summary_var, foreground="#555").pack(anchor="w", pady=(4, 0))

        columns = ("use", "confidence", "cluster", "members", "reason")
        self.tree = ttk.Treeview(self, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="")
        self.tree.column("#0", width=18, stretch=False)
        self.tree.heading("use", text="Об'єднати")
        self.tree.heading("confidence", text="Впевненість")
        self.tree.heading("cluster", text="Пропозиція")
        self.tree.heading("members", text="Блоків")
        self.tree.heading("reason", text="Причина")
        self.tree.column("use", width=80, anchor="center")
        self.tree.column("confidence", width=105, anchor="center")
        self.tree.column("cluster", width=500, anchor="w")
        self.tree.column("members", width=70, anchor="center")
        self.tree.column("reason", width=430, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.tree.bind("<Button-1>", self._click, add="+")
        self.tree.bind("<space>", self._space)

        for index, cluster in enumerate(self.clusters):
            titles = [groups[group_id].canonical_title for group_id in cluster.group_ids if group_id in groups]
            parent_id = f"cluster:{index}"
            self.tree.insert(
                "",
                "end",
                iid=parent_id,
                values=("☑", f"{cluster.confidence}%", " + ".join(titles[:2]), len(cluster.group_ids), cluster.reason),
                open=True,
                tags=("strong" if cluster.confidence >= 80 else "possible",),
            )
            for group_id in cluster.group_ids:
                group = groups.get(group_id)
                if group is None:
                    continue
                self.tree.insert(
                    parent_id,
                    "end",
                    iid=f"member:{index}:{group_id}",
                    values=("", "", f"#{group_id} · {group.canonical_title}", group.source_count, group.last_published_at or "—"),
                )
        self.tree.tag_configure("strong", background="#e5f5e5")
        self.tree.tag_configure("possible", background="#fff5d6")

        actions = ttk.Frame(self, padding=(12, 0, 12, 12))
        actions.pack(fill="x")
        ttk.Button(actions, text="Вибрати всі", command=self.select_all).pack(side="left")
        ttk.Button(actions, text="Зняти всі", command=self.clear_all).pack(side="left", padx=6)
        ttk.Button(actions, text="Закрити", command=self.destroy).pack(side="right")
        self.apply_button = ttk.Button(actions, text="Об'єднати вибрані блоки", command=self.apply)
        self.apply_button.pack(side="right", padx=(0, 8))
        self._update_summary()
        self.grab_set()
        self.focus_set()

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
        self.summary_var.set(
            f"Запропоновано блоків на об'єднання: {len(self.clusters)} · вибрано: {len(self.selected)}"
        )
        self.apply_button.configure(state="normal" if self.selected else "disabled")

    def apply(self) -> None:
        chosen = [self.clusters[index] for index in sorted(self.selected)]
        if not chosen:
            return
        self.grab_release()
        self.destroy()
        self.on_apply(chosen)
