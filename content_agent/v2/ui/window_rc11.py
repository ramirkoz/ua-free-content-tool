from __future__ import annotations

from ...version import APP_VERSION
from ..supervisor.resilient_runtime import ResilientSupervisorRuntime
from . import window as base_window
from .window_rc8 import MainWindow as Rc8MainWindow


class MainWindow(Rc8MainWindow):
    """RC11: Drive circuit breaker, durable History, self-healing collection."""

    VERSION_LABEL = APP_VERSION

    def __init__(self, root, database, config) -> None:
        base_window.SupervisorRuntime = ResilientSupervisorRuntime
        super().__init__(root, database, config)
        self._rc11_autocollect_watchdog_id = None
        self._rc11_schedule_autocollect_watchdog()

    def _apply_v2_labels(self) -> None:
        self.root.title(f"UA FREE Content Tool — v{APP_VERSION}")

    def _rc11_schedule_autocollect_watchdog(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            if getattr(self, "background_services_started", False):
                running = bool(getattr(self, "auto_collect_running", False))
                scheduled = getattr(self, "auto_collect_after_id", None)
                if not running and scheduled is None:
                    self._schedule_next_auto_collect()
            self._rc11_autocollect_watchdog_id = self.root.after(60000, self._rc11_schedule_autocollect_watchdog)
        except Exception:
            self._rc11_autocollect_watchdog_id = None
