from __future__ import annotations

import threading
from contextlib import contextmanager


class MaintenanceGate:
    """Process-wide shared/exclusive gate around destructive Data maintenance.

    Normal SQLite connections are shared and may coexist. Backup/import/restore use
    the gate as an exclusive context manager, which waits for active connections
    and blocks new ones until the maintenance transaction finishes.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0
        self._local = threading.local()

    @contextmanager
    def shared(self):
        # Re-entrant exclusive owner may open validation connections safely.
        if getattr(self._local, "exclusive_depth", 0) > 0:
            yield
            return
        with self._condition:
            while self._writer or self._waiting_writers > 0:
                self._condition.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._condition:
                self._readers -= 1
                if self._readers <= 0:
                    self._condition.notify_all()

    def __enter__(self):
        depth = int(getattr(self._local, "exclusive_depth", 0) or 0)
        if depth > 0:
            self._local.exclusive_depth = depth + 1
            return self
        with self._condition:
            self._waiting_writers += 1
            try:
                while self._writer or self._readers > 0:
                    self._condition.wait()
                self._writer = True
            finally:
                self._waiting_writers -= 1
        self._local.exclusive_depth = 1
        return self

    def __exit__(self, exc_type, exc, tb):
        depth = int(getattr(self._local, "exclusive_depth", 0) or 0)
        if depth > 1:
            self._local.exclusive_depth = depth - 1
            return False
        self._local.exclusive_depth = 0
        with self._condition:
            self._writer = False
            self._condition.notify_all()
        return False

    @property
    def active_readers(self) -> int:
        with self._condition:
            return int(self._readers)


DATA_MAINTENANCE_LOCK = MaintenanceGate()

__all__ = ["DATA_MAINTENANCE_LOCK", "MaintenanceGate"]
