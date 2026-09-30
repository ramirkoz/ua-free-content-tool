from __future__ import annotations

from dataclasses import dataclass

from ...destinations_v1_4 import destination_ready
from ...donation_settings_v1_3_1_rc8 import DonationSettings
from ...publisher_factory_v1_4 import V14PublisherFactory
from ...publishers import PublishContext, PublishError, Publisher
from .contracts import (
    AuthState,
    AuthStatus,
    Checkpoint,
    PlatformAdapter,
    PlatformCapabilities,
    PlatformPublishResult,
    PublishPayload,
)
from .outcomes import PublicationOutcome


@dataclass(frozen=True, slots=True)
class _AdapterShape:
    platform: str
    prefixes: tuple[str, ...]
    exact: tuple[str, ...]
    capabilities: PlatformCapabilities


class LegacyTransportAdapter(PlatformAdapter):
    """Typed RC52 boundary around the proven platform transports.

    Legacy publisher classes remain transport implementations.  Selection,
    authentication state and outcome semantics are owned here so workers/UI no
    longer need to understand concrete publisher classes.
    """

    def __init__(self, config, donation_settings: DonationSettings, shape: _AdapterShape) -> None:
        self.config = config
        self.donation_settings = donation_settings
        self.shape = shape
        self.platform = shape.platform
        self.capabilities = shape.capabilities
        self._factory = V14PublisherFactory(config, donation_settings)

    def matches(self, target_key: str) -> bool:
        key = str(target_key or "").strip()
        return key in self.shape.exact or any(key.startswith(prefix) for prefix in self.shape.prefixes)

    def auth_status(self, target_key: str) -> AuthStatus:
        key = str(target_key or "").strip()
        if not self.matches(key):
            return AuthStatus(AuthState.ERROR, "Ціль не належить цьому адаптеру.")
        try:
            if destination_ready(self.config, key):
                return AuthStatus(AuthState.CONNECTED)
        except Exception as exc:
            return AuthStatus(AuthState.ERROR, str(exc))
        enabled = bool(getattr(self.config, f"{self.platform}_enabled", True))
        if not enabled:
            return AuthStatus(AuthState.DISABLED, "Платформу вимкнено.")
        return AuthStatus(AuthState.MISSING, "Авторизація або обов'язкові параметри відсутні.")

    def create_publisher(self, target_key: str) -> Publisher:
        status = self.auth_status(target_key)
        if not status.connected:
            raise PublishError(status.detail or "Платформа не готова до публікації.", retryable=False, auth_error=True)
        return self._factory.create(target_key)

    def publish(
        self,
        payload: PublishPayload,
        checkpoint: Checkpoint,
        context: PublishContext,
    ) -> PlatformPublishResult:
        latest = dict(checkpoint.progress)

        def save_progress(progress: dict[str, object]) -> None:
            latest.clear()
            latest.update(progress)
            checkpoint.progress.clear()
            checkpoint.progress.update(progress)
            context.save_progress(progress)

        proxy = PublishContext(before_write=context.before_write, save_progress=save_progress)
        try:
            result = self.create_publisher(payload.target_key).publish(
                payload.text,
                latest,
                proxy,
                payload.media,
            )
        except PublishError as exc:
            outcome = PublicationOutcome.UNKNOWN if bool(exc.outcome_unknown) else PublicationOutcome.FAILED_KNOWN
            return PlatformPublishResult(
                outcome=outcome,
                checkpoint=dict(latest),
                error=str(exc),
                retryable=bool(exc.retryable) and outcome is not PublicationOutcome.UNKNOWN,
                auth_error=bool(exc.auth_error),
            )
        except Exception as exc:
            # A local/transport exception after before_write cannot prove that the
            # external platform did not accept the request. Fail closed.
            return PlatformPublishResult(
                outcome=PublicationOutcome.UNKNOWN,
                checkpoint=dict(latest),
                error=str(exc),
                retryable=False,
            )

        remote_id = str(result.remote_id or "").strip()
        progress = dict(result.progress)
        checkpoint.progress.clear()
        checkpoint.progress.update(progress)
        return PlatformPublishResult(
            outcome=PublicationOutcome.SENT,
            remote_id=remote_id,
            checkpoint=progress,
        )


class TelegramAdapter(LegacyTransportAdapter):
    def __init__(self, config, donation_settings: DonationSettings) -> None:
        super().__init__(
            config,
            donation_settings,
            _AdapterShape(
                "telegram",
                ("telegram:",),
                ("telegram",),
                PlatformCapabilities(gallery=False, comment=False, reply=False, donation_inline=True),
            ),
        )


class InstagramAdapter(LegacyTransportAdapter):
    def __init__(self, config, donation_settings: DonationSettings) -> None:
        super().__init__(
            config,
            donation_settings,
            _AdapterShape(
                "instagram",
                ("instagram:",),
                ("instagram",),
                PlatformCapabilities(gallery=True, comment=False, reply=False, donation_inline=True),
            ),
        )


class FacebookAdapter(LegacyTransportAdapter):
    def __init__(self, config, donation_settings: DonationSettings) -> None:
        super().__init__(
            config,
            donation_settings,
            _AdapterShape(
                "facebook",
                ("facebook:",),
                (),
                PlatformCapabilities(gallery=True, comment=True, reply=False, donation_comment=True),
            ),
        )


class ThreadsAdapter(LegacyTransportAdapter):
    def __init__(self, config, donation_settings: DonationSettings) -> None:
        super().__init__(
            config,
            donation_settings,
            _AdapterShape(
                "threads",
                (),
                ("threads",),
                PlatformCapabilities(gallery=True, comment=True, reply=True, donation_comment=True),
            ),
        )


class LinkedInAdapter(LegacyTransportAdapter):
    def __init__(self, config, donation_settings: DonationSettings) -> None:
        super().__init__(
            config,
            donation_settings,
            _AdapterShape(
                "linkedin",
                (),
                ("linkedin",),
                PlatformCapabilities(gallery=True, comment=True, reply=False, donation_inline=True),
            ),
        )
