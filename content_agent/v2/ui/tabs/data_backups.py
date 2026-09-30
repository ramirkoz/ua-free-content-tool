from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class DataBackupsTabController:
    """Operator-facing durable data, backup and retention controls."""

    def __init__(self, host) -> None:
        self.host = host
        self.notebook = host.notebook
        self.frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.frame, text="Дані й резервні копії")

        ttk.Label(self.frame, text="Дані й резервні копії", font="TkHeadingFont").pack(anchor="w")
        ttk.Label(
            self.frame,
            text=(
                "Робочі новини зберігаються 7 діб. Джерела, теми, налаштування, credentials, "
                "editorial learning та правила виключення не видаляються. Незавершені або UNKNOWN "
                "публікації захищені від автоматичного очищення."
            ),
            justify="left",
            wraplength=900,
        ).pack(anchor="w", pady=(8, 14))

        backup = ttk.LabelFrame(self.frame, text="Резервні копії", padding=10)
        backup.pack(fill="x", pady=(0, 12))
        ttk.Button(backup, text="Створити backup", command=host.create_backup_ui).pack(side="left", padx=(0, 8))
        ttk.Button(backup, text="Migration backup…", command=host.create_migration_backup_ui).pack(side="left", padx=(0, 8))
        ttk.Button(backup, text="Відновити з backup…", command=host.import_backup_ui).pack(side="left")

        retention = ttk.LabelFrame(self.frame, text="Очищення оперативної бази", padding=10)
        retention.pack(fill="x")
        self.status_var = tk.StringVar(master=host.root, value="Автоматично під час запуску: усе старше 7 діб.")
        ttk.Label(retention, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        ttk.Button(retention, text="Очистити зараз", command=self._purge_now).pack(side="right")

    def _purge_now(self) -> None:
        self.status_var.set("Очищення…")

        def action():
            return self.host.services.retention.purge(allow_vacuum=True)

        def success(result) -> None:
            self.status_var.set(
                f"Готово: видалено новин {result.deleted_articles}, блоків {result.deleted_groups}; "
                f"VACUUM: {'так' if result.vacuumed else 'не потрібен'}."
            )
            try:
                self.host.refresh_groups()
            except Exception:
                pass

        self.host.run_async(
            action,
            success,
            label="Очищаю оперативну базу",
            done_label="Оперативну базу очищено",
        )

    def refresh(self) -> None:
        return

    def focus_primary(self) -> None:
        self.frame.focus_set()

    def reset(self) -> None:
        return


__all__ = ["DataBackupsTabController"]
