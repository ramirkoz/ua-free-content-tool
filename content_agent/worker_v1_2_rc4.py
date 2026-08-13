from __future__ import annotations

import time
from typing import Any

from .worker import WorkerResult
from .worker_v1_2 import ManagedMediaPublicationWorker


class Rc4PublicationWorker(ManagedMediaPublicationWorker):
    CATCHUP_GAP_SECONDS = 5 * 60

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._catchup_not_before = 0.0

    def run_once(self) -> WorkerResult:
        remaining = self._catchup_not_before - time.monotonic()
        if remaining > 0:
            return WorkerResult(
                claimed=False,
                busy=True,
                pause_reason=f"Наступна прострочена новина не раніше ніж через {max(1, int(remaining))} с.",
            )
        return super().run_once()
