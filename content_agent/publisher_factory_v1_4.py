from __future__ import annotations

from .comment_compat_v1_2_rc3 import CompatibleTelegramPublisher
from .destinations_v1_4 import instagram_account_for_key, instagram_token_for
from .donation_settings_v1_3_1_rc8 import DonationSettings
from .instagram_target_v1_2_rc4 import InstagramTarget
from .publisher_factory_v1_3_1_rc8 import Rc8InstagramPublisher, Rc8PublisherFactory, Rc8TelegramPublisher
from .publishers import PublishContext, PublishError, PublishResult, Publisher
from .v2.publishing.adapters import (
    FACEBOOK_CAPABILITIES,
    INSTAGRAM_CAPABILITIES,
    LINKEDIN_CAPABILITIES,
    THREADS_CAPABILITIES,
    TELEGRAM_CAPABILITIES,
    PublisherPlatformAdapter,
)
from .v2.publishing.contracts import AuthState, AuthStatus, PublishPayload
from .v2.publishing.outcomes import PublicationOutcome
from .v2.publishing.registry import DestinationRegistry
from .v2.publishing.service import PublicationService


class _RegistryPublisher(Publisher):
    """Legacy worker-compatible publisher backed by RC52 PublicationService."""

    def __init__(self, factory: "V14PublisherFactory", destination: str) -> None:
        self.factory = factory
        self.destination = destination

    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media=None) -> PublishResult:
        settings = self.factory.donation_settings.normalized()
        family = self.destination.split(":", 1)[0]
        enabled = settings.enabled_for(self.destination)
        if not enabled and self.destination.startswith(("telegram:", "instagram:")):
            enabled = settings.enabled_for(family)
        attempt = self.factory.publication_service.publish(
            self.destination,
            PublishPayload(
                text=text,
                media=media,
                donation_text=settings.text,
                donation_enabled=enabled,
            ),
            progress=progress,
            before_write=context.before_write,
            save_progress=context.save_progress,
        )
        if attempt.outcome is PublicationOutcome.SENT:
            return PublishResult(remote_id=attempt.remote_id or None, progress=attempt.progress)
        raise PublishError(
            attempt.error or "Публікація не завершена.",
            retryable=attempt.automatic_retry_allowed,
            auth_error=attempt.auth_error,
            outcome_unknown=attempt.outcome is PublicationOutcome.UNKNOWN,
        )


class V14PublisherFactory(Rc8PublisherFactory):
    """Active platform factory routed through the RC52 typed publication boundary."""

    def __init__(self, config, donation_settings: DonationSettings):
        super().__init__(config, donation_settings)
        connected = lambda _destination: AuthStatus(AuthState.CONNECTED)
        adapters = [
            PublisherPlatformAdapter("telegram", self._create_transport, TELEGRAM_CAPABILITIES, connected),
            PublisherPlatformAdapter("facebook", self._create_transport, FACEBOOK_CAPABILITIES, connected),
            PublisherPlatformAdapter("instagram", self._create_transport, INSTAGRAM_CAPABILITIES, connected),
            PublisherPlatformAdapter("threads", self._create_transport, THREADS_CAPABILITIES, connected),
            PublisherPlatformAdapter("linkedin", self._create_transport, LINKEDIN_CAPABILITIES, connected),
        ]
        self.destination_registry = DestinationRegistry(adapters)
        self.publication_service = PublicationService(self.destination_registry)

    def _settings_for_payload(self, destination: str, payload: PublishPayload) -> DonationSettings:
        targets = [destination] if payload.donation_enabled and str(payload.donation_text or "").strip() else []
        return DonationSettings(text=str(payload.donation_text or ""), targets=targets)

    def _create_transport(self, platform: str, payload: PublishPayload) -> Publisher:
        """Create a proven concrete transport from immutable per-attempt policy."""
        key = str(platform or "").strip()
        settings = self._settings_for_payload(key, payload)
        donation_text = settings.text
        enabled = settings.enabled_for(key)

        if key.startswith("telegram:"):
            if not self.config.telegram_enabled or not self.config.telegram_bot_token:
                raise PublishError("Telegram вимкнено або bot token відсутній.", retryable=False, auth_error=True)
            chat_id = key.split(":", 1)[1].strip()
            if not chat_id:
                raise PublishError("Telegram destination не містить chat_id.", retryable=False, auth_error=True)
            return Rc8TelegramPublisher(
                CompatibleTelegramPublisher(self.config.telegram_bot_token, chat_id),
                donation_text=donation_text,
                enabled=enabled,
            )

        if key.startswith("instagram:"):
            if not self.config.instagram_enabled:
                raise PublishError("Instagram вимкнено в налаштуваннях.", retryable=False, auth_error=True)
            account = instagram_account_for_key(self.config, key)
            if account is None:
                raise PublishError(
                    f"Instagram-акаунт {key} не знайдено. Оновіть список акаунтів у налаштуваннях.",
                    retryable=False,
                    auth_error=True,
                )
            token = instagram_token_for(self.config, account)
            if not token:
                raise PublishError(
                    "Для цього Instagram-акаунта немає чинного Page Access Token. Оновіть Facebook Pages / Instagram у налаштуваннях.",
                    retryable=False,
                    auth_error=True,
                )
            return Rc8InstagramPublisher(
                InstagramTarget(account.id, token, self.config.meta_graph_version),
                donation_text=donation_text,
                enabled=enabled,
            )

        # Generic destinations keep the proven RC8 transports, but policy is a
        # per-attempt value rather than shared mutable factory configuration.
        return Rc8PublisherFactory(self.config, settings).create(key)

    def create(self, platform: str) -> Publisher:
        key = str(platform or "").strip()
        # Resolve before the worker starts any side effect. Drive is rejected here.
        self.destination_registry.resolve(key)
        return _RegistryPublisher(self, key)
