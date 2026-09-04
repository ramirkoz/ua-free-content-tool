from __future__ import annotations

import tkinter as tk

from .. import rewrite_pipeline_v1_3 as rewrite_pipeline_module
from ..rewrite_pipeline_v1_4_rc16 import candidate_after_router_rc16
from .v1_4_rc15_window import MainWindow as Rc15MainWindow


class MainWindow(Rc15MainWindow):
    """v1.4.0-rc16: multilingual Fact Guard reliability hotfix."""

    VERSION_LABEL = "1.4.0-rc16"

    def __init__(self, root: tk.Tk, database, config) -> None:
        # Activate the RC16 candidate selector only for an actual RC16 UI
        # instance. Importing content_agent.main during tests must not mutate
        # the v1.3 rewrite module globally.
        rewrite_pipeline_module._candidate_after_router = candidate_after_router_rc16
        super().__init__(root, database, config)
        self._apply_v14_labels()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc16")
