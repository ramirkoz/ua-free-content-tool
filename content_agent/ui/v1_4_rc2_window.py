from __future__ import annotations

from .v1_4_window import MainWindow as Rc1MainWindow


class MainWindow(Rc1MainWindow):
    """v1.4.0-rc2 hotfix window for Meta Instagram field compatibility."""

    VERSION_LABEL = "1.4.0-rc2"

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc2")
