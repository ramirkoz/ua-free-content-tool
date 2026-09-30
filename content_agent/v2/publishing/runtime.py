from __future__ import annotations

from typing import Any

from ...donation_settings_v1_3_1_rc8 import DonationSettings, load_donation_settings
from ...publisher_factory_v1_4 import V14PublisherFactory
from ...publishers import PublishContext, PublishError, PublishResult, Publisher
from .adapters import (
    FACEBOOK_CAPABILITIES,
    INSTAGRAM_CAPABILITIES,
    LINKEDIN_CAPABILITIES,
    THREADS_CAPABILITIES,
    TELEGRAM_CAPABILITIES,
    PublisherPlatformAdapter,
)
from .contracts import AuthState, AuthStatus, PublishPayload
from .outcomes import PublicationOutcome
from .registry import DestinationRegistry
from .service import PublicationService


def _payload_factory(config: Any):
    """Build a publisher from immutable per-attempt donation policy.

    A fresh legacy transport factory is used per attempt, so donation settings are
    no longer shared mutable factory state between destinations. The adapter layer
    owns policy; legacy classes remain transport compatibility until their HTTP
    implementations are extracted individually.
    """

    def build(destination: str, payload: PublishPayload) -> Publisher:
        targets = [destination] if payload.donation_enabled and payload.donation_text.strip() else []
        settings = DonationSettings(text=payload.donation_text, targets=targets)
        return V14PublisherFactory(config, settings).create(destination)

    return build


def _auth_probe(config: Any, family: str):
    def probe(destination: str) -> AuthStatus:
        try:
            if family == "telegram":
                ready = bool(getattr(config, "telegram_enabled", False) and getattr(config, "telegram_bot_token", ""))
            elif family == "instagram":
                ready = bool(getattr(config, "instagram_enabled", False))
            elif family == "facebook":
                page_id = destination.split(":", 1)[1] if ":" in destination else ""
                ready = bool(page_id and getattr(config, "facebook_page", lambda _x: None)(page_id))
            elif family == "threads":
                ready = bool(getattr(config, "threads_user_id", "") and getattr(config, "threads_token", ""))
            elif family == "linkedin":
                ready = bool(getattr(config, "linkedin_author_urn", "") and getattr(config, "linkedin_token", ""))
            else:
                ready = False
            return AuthStatus(AuthState.CONNECTED if ready else AuthState.NOT_CONFIGURED)
        except Exception as exc:
            return AuthStatus(AuthState.ERROR, str(exc))
    return probe


def build_destination_registry(config: Any) -> DestinationRegistry:
    builder = _payload_factory(config)
    return DestinationRegistry(
        [
            PublisherPlatformAdapter("telegram", builder, TELEGRAM_CAPABILITIES, _auth_probe(config, "telegram")),
            PublisherPlatformAdapter("facebook", builder, FACEBOOK_CAPABILITIES, _auth_probe(config, "facebook")),
            PublisherPlatformAdapter("instagram", builder, INSTAGRAM_CAPABILITIES, _auth_probe(config, "instagram")),
            PublisherPlatformAdapter("threads", builder, THREADS_CAPABILITIES, _auth_probe(config, "threads")),
            PublisherPlatformAdapter("linkedin", builder, LINKEDIN_CAPABILITIES, _auth_probe(config, "linkedin")),
        ]
    )


class RegistryPublisher(Publisher):
    def __init__(self, destination: str, service: PublicationService, settings: DonationSettings) -> None:
        self.destination = destination
        self.service = service
        self.settings = settings.normalized()

    def publish(self, text: str, progress: dict[str, object], context: PublishContext, media=None) -> PublishResult:
        attempt = self.service.publish(
            self.destination,
            PublishPayload(
                text=text,
                media=media,
                donation_text=self.settings.text,
                donation_enabled=self.settings.enabled_for(self.destination),
            ),
            progress=progress,
            before_write=context.before_write,
            save_progress=context.save_progress,
        )
        if attempt.outcome is PublicationOutcome.SENT:
            return PublishResult(remote_id=attempt.remote_id or None, progress=attempt.progress)
        raise PublishError(
            attempt.error or "Публікація не завершена.",
            retryable=bool(attempt.automatic_retry_allowed),
            auth_error=attempt.auth_error,
            outcome_unknown=attempt.outcome is PublicationOutcome.UNKNOWN,
        )


class RegistryPublisherFactory:
    """Legacy worker facade backed by the RC52 publication service."""

    def __init__(self, config: Any, service: PublicationService, settings: DonationSettings | None = None) -> None:
        self.config = config
        self.service = service
        self.donation_settings = (settings or load_donation_settings()).normalized()

    def update_donation_settings(self, settings: DonationSettings) -> None:
        self.donation_settings = settings.normalized()

    def create(self, platform: str) -> Publisher:
        # Resolve early so unsupported destinations fail before worker side effects.
        self.service.registry.resolve(platform)
        return RegistryPublisher(platform, self.service, self.donation_settings)


__all__ = ["RegistryPublisherFactory", "build_destination_registry"]
