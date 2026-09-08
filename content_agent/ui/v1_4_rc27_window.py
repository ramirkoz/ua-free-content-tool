from __future__ import annotations

from ..ai_router import install_runtime as install_router_runtime
from ..rewrite_pipeline_v1_4_rc27 import install_runtime as install_rewrite_runtime
from .v1_4_rc26_window import MainWindow as Rc26MainWindow


class MainWindow(Rc26MainWindow):
    """v1.4.0-rc27: stable public-copy parsing and balanced multi-source rewrite."""

    VERSION_LABEL = "1.4.0-rc27"

    def __init__(self, root, database, config) -> None:
        install_router_runtime()
        install_rewrite_runtime()
        super().__init__(root, database, config)
        # RC26's constructor reinstalls its own rewrite runtime.  RC27 must be the
        # final active layer after the complete inheritance chain finishes.
        install_router_runtime()
        install_rewrite_runtime()
        self._apply_v14_labels()
        self.refresh_ai_component_status()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc27")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        install_router_runtime()
        install_rewrite_runtime()
        self._apply_v14_labels()
