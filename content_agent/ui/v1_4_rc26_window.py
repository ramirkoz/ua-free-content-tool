from __future__ import annotations

from ..ai_router import install_runtime as install_router_runtime
from ..rewrite_pipeline_v1_4_rc26 import install_runtime as install_rewrite_runtime
from .v1_4_rc25_window import MainWindow as Rc25MainWindow


class MainWindow(Rc25MainWindow):
    """v1.4.0-rc26: resilient rewrite envelope and cloud format recovery."""

    VERSION_LABEL = "1.4.0-rc26"

    def __init__(self, root, database, config) -> None:
        # Install only when a real RC26 window is built. Importing the module in
        # regression tests must not mutate the historical v1.3 pipeline globally.
        install_router_runtime()
        install_rewrite_runtime()
        super().__init__(root, database, config)
        install_router_runtime()
        install_rewrite_runtime()
        self._apply_v14_labels()
        self.refresh_ai_component_status()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc26")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        install_router_runtime()
        install_rewrite_runtime()
        self._apply_v14_labels()
