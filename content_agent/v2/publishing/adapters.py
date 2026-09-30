from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ...publishers import PublishContext, PublishError, Publisher
from .contracts import AuthState, AuthStatus, PlatformCapabilities, PublishAttempt, PublishPayload
from .outcomes import PublicationOutcome


PublisherBuilder = Callable[[str, PublishPayload], Publisher]
AuthProbe = Callable[[str], AuthStatus]


@dataclass(slots=True)
class PublisherPlatformAdapter:
    """Typed adapter around an existing, proven platform transport.

    Donation policy belongs to ``PublishPayload`` and is passed to the builder;
    adapters never mutate module globals. This makes parallel destinations safe.
    """

    family: str
    builder: PublisherBuilder
    capabilities: PlatformCapabilities
    auth_probe: AuthProbe | None = None

    def matches(self, destination: str) -> bool:
        key = str(destination or "").strip().casefold()
        return key == self.family or key.startswith(self.family + ":")

    def auth_status(self, destination: str) -> AuthStatus:
        if self.auth_probe is None:
            return AuthStatus(AuthState.CONNECTED, "Auth is validated when the destination publisher is created.")
        try:
            return self.auth_probe(destination)
        except Exception as exc:
            return AuthStatus(AuthState.ERROR, str(exc))

    def publish(
        self,
        destination: str,
        payload: PublishPayload,
        *,
        progress: Mapping[str, Any] | None = None,
        before_write: Callable[[], None] | None = None,
        save_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> PublishAttempt:
        current = dict(progress or {})
        save = save_progress or (lambda _value: None)
        before = before_write or (lambda: None)
        try:
            publisher = self.builder(destination, payload)
            result = publisher.publish(
                payload.text,
                current,
                PublishContext(before_write=before, save_progress=save),
                payload.media,
            )
            return PublishAttempt(
                outcome=PublicationOutcome.SENT,
                remote_id=str(result.remote_id or ""),
                progress=dict(result.progress or {}),
            )
        except PublishError as exc:
            outcome = PublicationOutcome.UNKNOWN if bool(getattr(exc, "outcome_unknown", False)) else PublicationOutcome.FAILED_KNOWN
            return PublishAttempt(
                outcome=outcome,
                progress=current,
                error=str(exc),
                retryable=bool(getattr(exc, "retryable", False)) and outcome is PublicationOutcome.FAILED_KNOWN,
                auth_error=bool(getattr(exc, "auth_error", False)),
            )
        except Exception as exc:
            # Unknown exceptions may have happened after an external write. Fail
            # closed rather than guessing that the post was not created.
            return PublishAttempt(
                outcome=PublicationOutcome.UNKNOWN,
                progress=current,
                error=str(exc),
                retryable=False,
            )


TELEGRAM_CAPABILITIES = PlatformCapabilities(text=True, image=True, video=True, gallery=True, comments=False, multi_account=True)
FACEBOOK_CAPABILITIES = PlatformCapabilities(text=True, image=True, video=True, gallery=True, comments=True, multi_account=True)
INSTAGRAM_CAPABILITIES = PlatformCapabilities(text=True, image=True, video=True, gallery=True, comments=False, multi_account=True)
THREADS_CAPABILITIES = PlatformCapabilities(text=True, image=True, video=False, gallery=True, comments=True, multi_account=False)
LINKEDIN_CAPABILITIES = PlatformCapabilities(text=True, image=True, video=True, gallery=True, comments=True, multi_account=False)


__all__ = [
    "FACEBOOK_CAPABILITIES",
    "INSTAGRAM_CAPABILITIES",
    "LINKEDIN_CAPABILITIES",
    "PublisherPlatformAdapter",
    "THREADS_CAPABILITIES",
    "TELEGRAM_CAPABILITIES",
]
