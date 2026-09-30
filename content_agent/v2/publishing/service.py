from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping

from .contracts import AuthState, PublishAttempt, PublishPayload
from .outcomes import PublicationOutcome
from .registry import DestinationError, DestinationRegistry


class PublicationService:
    """Single orchestration boundary for external publication writes."""

    def __init__(self, registry: DestinationRegistry) -> None:
        self.registry = registry
        self._condition = threading.Condition()
        self._in_flight = 0
        self._closing = False

    @property
    def in_flight(self) -> int:
        with self._condition:
            return self._in_flight

    @property
    def closing(self) -> bool:
        with self._condition:
            return self._closing

    def publish(
        self,
        destination: str,
        payload: PublishPayload,
        *,
        progress: Mapping[str, Any] | None = None,
        before_write: Callable[[], None] | None = None,
        save_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> PublishAttempt:
        with self._condition:
            if self._closing:
                return PublishAttempt(
                    outcome=PublicationOutcome.NOT_ATTEMPTED,
                    error="Publication service is closing; no new external write was started.",
                    retryable=False,
                )
            self._in_flight += 1
        try:
            try:
                entry = self.registry.resolve(destination)
            except DestinationError as exc:
                return PublishAttempt(
                    outcome=PublicationOutcome.FAILED_KNOWN,
                    error=str(exc),
                    retryable=False,
                )
            auth = entry.adapter.auth_status(destination)
            if auth.state is not AuthState.CONNECTED:
                return PublishAttempt(
                    outcome=PublicationOutcome.FAILED_KNOWN,
                    error=auth.message or f"Platform authentication is {auth.state.value}.",
                    retryable=False,
                    auth_error=True,
                )
            attempt = entry.adapter.publish(
                destination,
                payload,
                progress=progress,
                before_write=before_write,
                save_progress=save_progress,
            )
            # Ambiguous results are always terminal until the operator resolves
            # them as SENT or CONFIRMED_NOT_SENT. Never auto-retry UNKNOWN.
            if attempt.outcome is PublicationOutcome.UNKNOWN:
                attempt.retryable = False
            return attempt
        finally:
            with self._condition:
                self._in_flight -= 1
                self._condition.notify_all()

    @staticmethod
    def can_automatically_retry(attempt: PublishAttempt) -> bool:
        return bool(
            attempt.outcome is PublicationOutcome.FAILED_KNOWN
            and attempt.retryable
            and not attempt.auth_error
        )

    def close(self, timeout: float = 30.0) -> bool:
        """Stop accepting new publishes and wait for the current safe boundary."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            self._closing = True
            while self._in_flight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(min(0.25, remaining))
            return True


__all__ = ["PublicationService"]
