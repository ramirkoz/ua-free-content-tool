from __future__ import annotations

from .window_rc7 import MainWindow as Rc7MainWindow


class MainWindow(Rc7MainWindow):
    """RC8: provider recovery plus remote supervisor control/update."""

    VERSION_LABEL = "2.0.0-rc8"

    def _apply_v2_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v2.0.0-rc8")
