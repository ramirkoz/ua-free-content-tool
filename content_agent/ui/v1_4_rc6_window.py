from __future__ import annotations

from .v1_4_rc5_window import MainWindow as Rc5MainWindow


class MainWindow(Rc5MainWindow):
    """v1.4.0-rc6: duplicate-review footer and confidence semantics fix."""

    VERSION_LABEL = "1.4.0-rc6"

    def _apply_v14_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v1.4.0-rc6")
