from __future__ import annotations

from tkinter import filedialog, simpledialog, ttk
from pathlib import Path


class DataTabController:
    def __init__(self, owner) -> None:
        self.owner = owner
        self.tab = None
        self.status_var = None

    def build(self) -> None:
        if self.tab is not None:
            return
        tab = ttk.Frame(self.owner.notebook, padding=12)
        self.owner.notebook.add(tab, text="Дані й backup")
        self.tab = tab
        self.status_var = self.owner.status_var.__class__(master=self.owner.root, value="Звичайний backup не містить переносимих credentials.")

        ttk.Label(tab, text="Дані й резервні копії", font="TkHeadingFont").pack(anchor="w")
        ttk.Label(
            tab,
            text=(
                "Звичайний backup містить базу, durable state та publication receipts, але не переносимі credentials. "
                "Для переносу на інший ПК використовуйте окремий migration backup із паролем."
            ),
            wraplength=1100,
            foreground="#555",
        ).pack(anchor="w", fill="x", pady=(6, 12))
        actions = ttk.Frame(tab)
        actions.pack(fill="x")
        ttk.Button(actions, text="Створити backup", command=self.owner.create_backup_ui).pack(side="left")
        ttk.Button(actions, text="Migration backup…", command=self.owner.create_migration_backup_ui).pack(side="left", padx=6)
        ttk.Button(actions, text="Імпортувати backup…", command=self.owner.import_backup_ui).pack(side="left")
        ttk.Label(tab, textvariable=self.status_var, wraplength=1100).pack(anchor="w", fill="x", pady=(12, 0))

    def choose_password(self, *, confirm: bool) -> str | None:
        first = simpledialog.askstring(
            "Migration backup",
            "Пароль (мінімум 10 символів):",
            parent=self.owner.root,
            show="•",
        )
        if first is None:
            return None
        if len(first) < 10:
            self.owner.msg.showwarning("Migration backup", "Пароль має містити щонайменше 10 символів.", parent=self.owner.root)
            return None
        if not confirm:
            return first
        second = simpledialog.askstring("Migration backup", "Повторіть пароль:", parent=self.owner.root, show="•")
        if second != first:
            self.owner.msg.showwarning("Migration backup", "Паролі не збігаються.", parent=self.owner.root)
            return None
        return first
