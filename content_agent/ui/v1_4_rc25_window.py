from __future__ import annotations

from ..ai_router import install_runtime
from .v1_4_rc24_window import MainWindow as Rc24MainWindow

# The inheritance chain imports historical router layers. RC25 is always applied
# last, before and after the base window builds its controls.
install_runtime()


class MainWindow(Rc24MainWindow):
    """v1.4.0-rc25: health-aware provider pool and resilient transport."""

    VERSION_LABEL = "1.4.0-rc25"

    def __init__(self, root, database, config) -> None:
        install_runtime()
        super().__init__(root, database, config)
        install_runtime()
        self._apply_v14_labels()
        self.refresh_ai_component_status()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc25")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        install_runtime()
        self._apply_v14_labels()
