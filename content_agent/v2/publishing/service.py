from __future__ import annotations

from threading import Condition, RLock

from ...donation_settings_v1_3_1_rc8 import DonationSettings, load_donation_settings
from ...publishers import PublishContext, PublishError, Publisher, PublishResult
from .adapters import FacebookAdapter, InstagramAdapter, LinkedInAdapter, TelegramAdapter, ThreadsAdapter
from .contracts import Checkpoint, PlatformPublishResult, PublishPayload
from .outcomes import PublicationOutcome
from .registry import DestinationRegistry


class _AdapterPublisher(Publisher):
    """Compatibility facade for the existing publication worker.

    The worker can keep its stable Publisher API while all target selection,
    authentication and outcome semantics go through RC52 adapters.
    """

    def __init__(self, service: "PublishingService", target_key: str) -> None:
        self.service = service
        self.target_key = target_key

    def publish(self, text, progress, context: PublishContext, media=None) -> PublishResult:
        result = self.service.publish(
            PublishPayload(target_key=self.target_key, text=text, media=media),
            Checkpoint(dict(progress)),
            context,
        )
        if result.outcome is PublicationOutcome.SENT:
            return PublishResult(remote_id=result.remote_id or None, progress=dict(result.checkpoint))
        error = PublishError(
            result.error or f"{self.target_key}: публікація не завершена.",
            retryable=bool(result.retryable),
            auth_error=bool(result.auth_error),
            outcome_unknown=result.outcome is PublicationOutcome.UNKNOWN,
        )
        raise error


class PlatformPublisherFactory:
    """Stable worker-facing factory backed by DestinationRegistry."""

    def __init__(self, service: "PublishingService") -> None:
        self.service = service
        self.config = service.config

    def create(self, platform: str) -> Publisher:
        self.service.registry.adapter_for(platform)
        return _AdapterPublisher(self.service, platform)


class PublishingService:
    """RC52 publication composition and in-flight lifecycle boundary."""

    def __init__(self, config, donation_settings: DonationSettings | None = None) -> None:
        self.config = config
        self.donation_settings = (donation_settings or load_donation_settings()).normalized()
        adapters = (
            TelegramAdapter(config, self.donation_settings),
            InstagramAdapter(config, self.donation_settings),
            FacebookAdapter(config, self.donation_settings),
            ThreadsAdapter(config, self.donation_settings),
            LinkedInAdapter(config, self.donation_settings),
        )
        self.registry = DestinationRegistry(config, adapters)
        self.publisher_factory = PlatformPublisherFactory(self)
        self._lifecycle = Condition(RLock())
        self._inflight = 0
        self._closing = False

    @property
    def inflight(self) -> int:
        with self._lifecycle:
            return int(self._inflight)

    @property
    def closing(self) -> bool:
        with self._lifecycle:
            return bool(self._closing)

    def update_donation_settings(self, settings: DonationSettings) -> None:
        normalized = settings.normalized()
        with self._lifecycle:
            if self._inflight:
                raise RuntimeError("Не можна змінювати publication policy під час активної зовнішньої публікації.")
            self.donation_settings = normalized
            adapters = (
                TelegramAdapter(self.config, normalized),
                InstagramAdapter(self.config, normalized),
                FacebookAdapter(self.config, normalized),
                ThreadsAdapter(self.config, normalized),
                LinkedInAdapter(self.config, normalized),
            )
            self.registry = DestinationRegistry(self.config, adapters)

    def publish(
        self,
        payload: PublishPayload,
        checkpoint: Checkpoint,
        context: PublishContext,
    ) -> PlatformPublishResult:
        with self._lifecycle:
            if self._closing:
                return PlatformPublishResult(
                    outcome=PublicationOutcome.NOT_ATTEMPTED,
                    checkpoint=dict(checkpoint.progress),
                    error="Програма завершує роботу; нову зовнішню публікацію не розпочато.",
                    retryable=False,
                )
            self._inflight += 1
        try:
            adapter = self.registry.adapter_for(payload.target_key)
            return adapter.publish(payload, checkpoint, context)
        finally:
            with self._lifecycle:
                self._inflight = max(0, self._inflight - 1)
                self._lifecycle.notify_all()

    def begin_shutdown(self) -> None:
        with self._lifecycle:
            self._closing = True
            self._lifecycle.notify_all()

    def wait_for_safe_boundary(self, timeout_seconds: float = 30.0) -> bool:
        timeout = max(0.0, float(timeout_seconds))
        with self._lifecycle:
            if self._inflight == 0:
                return True
            return self._lifecycle.wait_for(lambda: self._inflight == 0, timeout=timeout)
