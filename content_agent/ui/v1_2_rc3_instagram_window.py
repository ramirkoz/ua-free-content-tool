from __future__ import annotations

from tkinter import ttk

from .v1_2_rc3_window import MainWindow as RC3MainWindow


class MainWindow(RC3MainWindow):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._add_instagram_placeholder()

    def _add_instagram_placeholder(self) -> None:
        for tab_id in self.notebook.tabs():
            if str(self.notebook.tab(tab_id, "text")) != "Налаштування":
                continue
            tab = self.root.nametowidget(tab_id)
            box = ttk.LabelFrame(tab, text="Instagram", padding=8)
            box.pack(side="bottom", fill="x", padx=4, pady=(4, 8))
            ttk.Label(
                box,
                text=(
                    "Інтеграцію додано до RC3, але акаунт ще не підключено. "
                    "Instagram відображається у виборі платформ вимкненим. "
                    "Токени й авторизацію налаштуємо окремо, коли платформа знадобиться."
                ),
                foreground="#555",
                wraplength=1050,
            ).pack(fill="x")
            return
