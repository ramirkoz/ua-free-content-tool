from __future__ import annotations

from .v1_4_rc12_window import MainWindow as Rc12MainWindow


class MainWindow(Rc12MainWindow):
    """v1.4.0-rc13: exact per-destination scheduling intervals."""

    VERSION_LABEL = "1.4.0-rc13"

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc13")
