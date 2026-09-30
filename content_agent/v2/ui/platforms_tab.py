from __future__ import annotations

from tkinter import ttk


class PlatformsTabController:
    """Unified operator view of publishers and media services."""

    def __init__(self, owner, registry) -> None:
        self.owner = owner
        self.registry = registry
        self.tab = None
        self.tree = None

    def build(self) -> None:
        if self.tab is not None:
            return
        tab = ttk.Frame(self.owner.notebook, padding=12)
        self.owner.notebook.add(tab, text="Платформи")
        self.tab = tab
        ttk.Label(tab, text="Платформи й призначення", font="TkHeadingFont").pack(anchor="w")
        ttk.Label(
            tab,
            text="Google Drive показується як медіасервіс, а не як платформа публікації. Credentials редагуються у «Налаштуваннях».",
            foreground="#555", wraplength=1100,
        ).pack(anchor="w", fill="x", pady=(4, 8))
        columns = ("label", "role", "state")
        tree = ttk.Treeview(tab, columns=columns, show="headings", height=14)
        tree.heading("label", text="Профіль / канал / сервіс")
        tree.heading("role", text="Роль")
        tree.heading("state", text="Стан")
        tree.column("label", width=560, stretch=True)
        tree.column("role", width=160, stretch=False)
        tree.column("state", width=180, stretch=False)
        tree.pack(fill="both", expand=True)
        self.tree = tree
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="Оновити", command=self.refresh).pack(side="left")
        ttk.Button(actions, text="Перевірити підключення", command=lambda: self.owner.run_connection_diagnostics(automatic=False)).pack(side="left", padx=6)
        ttk.Button(actions, text="Відкрити налаштування", command=self._open_settings).pack(side="left")
        self.refresh()

    def refresh(self) -> None:
        if self.tree is None:
            return
        self.tree.delete(*self.tree.get_children(""))
        for item in self.registry.descriptors():
            role = "Медіасервіс" if item.role == "media_source" else "Публікація"
            state = "Готово" if item.configured else "Не налаштовано"
            self.tree.insert("", "end", iid=item.key, values=(item.label, role, state))

    def _open_settings(self) -> None:
        for tab_id in self.owner.notebook.tabs():
            if str(self.owner.notebook.tab(tab_id, "text")) == "Налаштування":
                self.owner.notebook.select(tab_id)
                return
