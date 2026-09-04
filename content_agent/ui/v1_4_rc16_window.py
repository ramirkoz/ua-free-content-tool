from __future__ import annotations

import tkinter as tk

from .v1_4_rc15_window import MainWindow as Rc15MainWindow


class MainWindow(Rc15MainWindow):
    """v1.4.0-rc16: multilingual Fact Guard numeric normalization hotfix."""

    VERSION_LABEL = "1.4.0-rc16"

    def __init__(self, root: tk.Tk, database, config) -> None:
        super().__init__(root, database, config)
        self._apply_v14_labels()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc16")
