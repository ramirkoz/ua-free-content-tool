from __future__ import annotations

from ..supervisor.resilient_runtime import ResilientSupervisorRuntime
from . import window as base_window
from .window_rc8 import MainWindow as Rc8MainWindow


class MainWindow(Rc8MainWindow):
    """RC9: publication reconciliation plus resilient supervisor telemetry."""

    VERSION_LABEL = "2.0.0-rc9"

    def __init__(self, root, database, config) -> None:
        # The V2 shell constructs SupervisorRuntime inside the base window module.
        # Swap that dependency before entering the inherited constructor, rather than
        # duplicating the entire 30k UI implementation for one service change.
        base_window.SupervisorRuntime = ResilientSupervisorRuntime
        super().__init__(root, database, config)

    def _apply_v2_labels(self) -> None:
        self.root.title("UA FREE Content Tool — v2.0.0-rc9")
