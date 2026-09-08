from __future__ import annotations

from ..ai_router import install_runtime

# RC22 window installs its own compatibility router while importing. Re-install
# RC23 immediately afterwards so every inherited rewrite consumer points at the
# absolute-deadline router.
from .v1_4_rc22_window import MainWindow as Rc22MainWindow

install_runtime()


class MainWindow(Rc22MainWindow):
    """v1.4.0-rc23: rewrite watchdog and router share one absolute deadline."""

    VERSION_LABEL = "1.4.0-rc23"

    def __init__(self, root, database, config) -> None:
        install_runtime()
        super().__init__(root, database, config)
        install_runtime()
        self._apply_v14_labels()
        self.refresh_ai_component_status()

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc23")

    def _apply_language(self, refresh: bool = True) -> None:
        super()._apply_language(refresh=refresh)
        install_runtime()
        self._apply_v14_labels()
