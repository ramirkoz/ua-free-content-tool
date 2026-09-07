from __future__ import annotations

from ..ai_router_v1_4_rc25 import install_runtime as install_router_runtime
from ..rewrite_pipeline_v1_4_rc26 import install_runtime as install_rewrite_runtime
from .v1_4_rc25_window import MainWindow as Rc25MainWindow

install_router_runtime()
install_rewrite_runtime()


class MainWindow(Rc25MainWindow):
    """v1.4.0-rc26: resilient rewrite envelope and cloud format recovery."""

    VERSION_LABEL = "1.4.0-rc26"

    def __init__(self, root, database, config) -> None:
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
