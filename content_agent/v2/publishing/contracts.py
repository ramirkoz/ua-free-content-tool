from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from ...models import MediaPayload
from ...publishers import PublishContext
from .outcomes import PublicationOutcome


class AuthState(StrEnum):
    CONNECTED = "connected"
    EXPIRED = "expired"
    MISSING = "missing"
    ERROR = "error"
    DISABLED = "disabled"


class AuthErrorKind(StrEnum):
    MISSING_CREDENTIALS = "missing_credentials"
    EXPIRED = "expired"
    PERMISSION = "permission"
    CONFIGURATION = "configuration"
    NETWORK = "network"
    UNKNOWN = "unknown"


class PlatformAuthError(RuntimeError):
    def __init__(self, message: str, *, kind: AuthErrorKind, retryable: bool = False) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = bool(retryable)


@dataclass(frozen=True, slots=True)
class AuthStatus:
    state: AuthState
    detail: str = ""

    @property
    def connected(self) -> bool:
        return self.state is AuthState.CONNECTED


@dataclass(frozen=True, slots=True)
class PlatformCapabilities:
    text: bool = True
    image: bool = True
    video: bool = True
    gallery: bool = False
    comment: bool = False
    reply: bool = False
    donation_inline: bool = False
    donation_comment: bool = False


@dataclass(frozen=True, slots=True)
class PublishPayload:
    target_key: str
    text: str
    media: MediaPayload | object | None = None
    donation_text: str = ""
    donation_enabled: bool = False


@dataclass(slots=True)
class Checkpoint:
    progress: dict[str, object] = field(default_factory=dict)

    def copy(self) -> "Checkpoint":
        return Checkpoint(dict(self.progress))


@dataclass(frozen=True, slots=True)
class PlatformPublishResult:
    outcome: PublicationOutcome
    remote_id: str = ""
    checkpoint: dict[str, object] = field(default_factory=dict)
    error: str = ""
    retryable: bool = False
    auth_error: bool = False


@runtime_checkable
class Authenticator(Protocol):
    def status(self, target_key: str) -> AuthStatus: ...


@runtime_checkable
class PlatformAdapter(Protocol):
    platform: str
    capabilities: PlatformCapabilities

    def matches(self, target_key: str) -> bool: ...
    def auth_status(self, target_key: str) -> AuthStatus: ...
    def publish(
        self,
        payload: PublishPayload,
        checkpoint: Checkpoint,
        context: PublishContext,
    ) -> PlatformPublishResult: ...


@runtime_checkable
class MediaService(Protocol):
    def inspect(self, file_id: str): ...
    def download(self, file_id: str): ...
