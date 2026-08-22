from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

from ..database import Database


class ContentExclusionsDialog:
    def __init__(
        self,
        parent: tk.Misc,
        database: Database,
        *,
        language: str = "uk",
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.db = database
        self.language = "en" if language == "en" else "uk"
        self.on_change = on_change
        self.window = tk.Toplevel(parent)
        self.window.title(self._t("Керування виключеннями", "Manage exclusions"))
        self.window.geometry("980x650")
        self.window.minsize(720, 480)
        self.window.transient(parent)

        actions = ttk.Frame(self.window, padding=8)
        actions.pack(fill="x")
        ttk.Button(actions, text=self._t("Оновити", "Refresh"), command=self.refresh).pack(side="left")
        ttk.Button(
            actions,
            text=self._t("Вимкнути вибрані", "Deactivate selected"),
            command=self.deactivate_selected,
        ).pack(side="left", padx=6)
        ttk.Button(
            actions,
            text=self._t("Очистити всі активні", "Clear all active"),
            command=self.clear_all,
        ).pack(side="left")
        ttk.Button(actions, text=self._t("Закрити", "Close"), command=self.window.destroy).pack(side="right")

        body = ttk.Panedwindow(self.window, orient="vertical")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        top = ttk.Frame(body)
        bottom = ttk.Frame(body)
        body.add(top, weight=3)
        body.add(bottom, weight=2)

        columns = ("id", "title", "updated")
        self.tree = ttk.Treeview(top, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("id", text="ID")
        self.tree.heading("title", text=self._t("Заголовок", "Title"))
        self.tree.heading("updated", text=self._t("Оновлено", "Updated"))
        self.tree.column("id", width=70, anchor="w")
        self.tree.column("title", width=650, anchor="w")
        self.tree.column("updated", width=190, anchor="w")
        scroll = ttk.Scrollbar(top, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.show_selected())

        ttk.Label(bottom, text=self._t("Збережений зразок", "Stored sample")).pack(anchor="w")
        self.preview = ScrolledText(bottom, wrap="word", height=10)
        self.preview.pack(fill="both", expand=True)
        self.preview.configure(state="disabled")
        self.rows: dict[int, dict[str, object]] = {}
        self.refresh()

    def _t(self, uk: str, en: str) -> str:
        return en if self.language == "en" else uk

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.rows = {int(row["id"]): row for row in self.db.list_content_exclusions(limit=5000)}
        for exclusion_id, row in self.rows.items():
            self.tree.insert(
                "", "end", iid=str(exclusion_id),
                values=(exclusion_id, str(row.get("title") or ""), str(row.get("updated_at") or "")),
            )
        self.show_selected()

    def show_selected(self) -> None:
        selected = self.tree.selection()
        text = ""
        if selected:
            row = self.rows.get(int(selected[0]))
            if row:
                text = str(row.get("source_text") or "")
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    def deactivate_selected(self) -> None:
        ids = [int(value) for value in self.tree.selection()]
        if not ids:
            messagebox.showinfo(
                self._t("Виключення", "Exclusions"),
                self._t("Оберіть хоча б один запис.", "Select at least one entry."),
                parent=self.window,
            )
            return
        changed = self.db.deactivate_content_exclusions(ids)
        if changed and self.on_change:
            self.on_change()
        self.refresh()

    def clear_all(self) -> None:
        if not self.rows:
            return
        if not messagebox.askyesno(
            self._t("Очистити виключення", "Clear exclusions"),
            self._t(
                "Вимкнути всі активні правила виключення? Старі відхилені блоки не відновляться автоматично, але нові схожі матеріали знову надходитимуть у Вхідні.",
                "Deactivate all active exclusion rules? Previously rejected blocks will not be restored automatically, but new similar items will return to Inbox.",
            ),
            parent=self.window,
        ):
            return
        changed = self.db.clear_content_exclusions()
        if changed and self.on_change:
            self.on_change()
        self.refresh()
