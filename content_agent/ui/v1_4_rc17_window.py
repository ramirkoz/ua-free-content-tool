from __future__ import annotations

import tkinter as tk

from .. import rewrite_pipeline_v1_3 as rewrite_pipeline_module
from ..rewrite_pipeline_v1_4_rc17 import candidate_after_router_rc17, install_rc17_fact_guard
from .v1_4_rc15_window import MainWindow as Rc15MainWindow


class MainWindow(Rc15MainWindow):
    """v1.4.0-rc17: entity-safe Fact Guard and bounded repair routing."""

    VERSION_LABEL = "1.4.0-rc17"

    def __init__(self, root: tk.Tk, database, config) -> None:
        install_rc17_fact_guard()
        rewrite_pipeline_module._candidate_after_router = candidate_after_router_rc17
        super().__init__(root, database, config)
        self._apply_v14_labels()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc17")
