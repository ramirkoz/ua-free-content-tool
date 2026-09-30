from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from .outcomes import PublicationOutcome


class AuthState(StrEnum):
    CONNECTED = "connected"
    EXPIRED = "expired"
    ERROR = "error"
    NOT_CONFIGURED = "not_configured"


class PlatformAuthError(RuntimeError):
    def __init__(self, message: str, *, state: AuthState = AuthState.ERROR) -> None:
        super().__init__(message)
        self.state = state


@dataclass(frozen=True, slots=True)
class AuthStatus:
    state: AuthState
    message: str = ""

    @property
    def ready(self) -> bool:
        return self.state is AuthState.CONNECTED


@dataclass(frozen=True, slots=True)
class PlatformCapabilities:
    text: bool = True
    image: bool = False
    video: bool = False
    gallery: bool = False
    comments: bool = False
    multi_account: bool = False


@dataclass(slots=True)
class PublishPayload:
    text: str
    media: Any = None
    donation_text: str = ""
    donation_enabled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PublishAttempt:
    outcome: PublicationOutcome
    remote_id: str = ""
    progress: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    retryable: bool = False
    auth_error: bool = False

    @property
    def sent(self) -> bool:
        return self.outcome is PublicationOutcome.SENT

    @property
    def automatic_retry_allowed(self) -> bool:
        return self.outcome is PublicationOutcome.FAILED_KNOWN and self.retryable


@runtime_checkable
class Authenticator(Protocol):
    def status(self, destination: str) -> AuthStatus: ...


@runtime_checkable
class PlatformAdapter(Protocol):
    family: str
    capabilities: PlatformCapabilities

    def matches(self, destination: str) -> bool: ...
    def auth_status(self, destination: str) -> AuthStatus: ...
    def publish(
        self,
        destination: str,
        payload: PublishPayload,
        *,
        progress: Mapping[str, Any] | None = None,
        before_write: Callable[[], None] | None = None,
        save_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> PublishAttempt: ...


@runtime_checkable
class MediaService(Protocol):
    """Media/storage service. It is deliberately not a publication adapter."""

    def ready(self) -> bool: ...


__all__ = [
    "AuthState",
    "AuthStatus",
    "Authenticator",
    "MediaService",
    "PlatformAdapter",
    "PlatformAuthError",
    "PlatformCapabilities",
    "PublishAttempt",
    "PublishPayload",
]
