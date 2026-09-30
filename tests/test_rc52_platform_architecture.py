from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from content_agent.app.container import build_services
from content_agent.donation_settings_v1_3_1_rc8 import DonationSettings
from content_agent.publishers import PublishContext, PublishError, PublishResult
from content_agent.v2.publishing import (
    AuthState,
    Checkpoint,
    DestinationRegistry,
    GoogleDriveMediaService,
    PlatformPublisherFactory,
    PublicationOutcome,
    PublishPayload,
    PublishingService,
)
from content_agent.v2.publishing.adapters import (
    FacebookAdapter,
    InstagramAdapter,
    LinkedInAdapter,
    TelegramAdapter,
    ThreadsAdapter,
)


class FakeConfig:
    telegram_enabled = True
    telegram_bot_token = "token"
    telegram_chat_id = "-1001"
    instagram_enabled = True
    instagram_user_id = "ig1"
    instagram_profile_name = "ig"
    instagram_token = "igtoken"
    meta_graph_version = "v23.0"
    facebook_pages = [{"id": "fb1", "name": "Page", "access_token": "fbtoken"}]
    threads_enabled = True
    threads_user_id = "th1"
    threads_profile_name = "Threads"
    threads_token = "thtoken"
    linkedin_enabled = True
    linkedin_author_urn = "urn:li:person:1"
    linkedin_profile_name = "LinkedIn"
    linkedin_token = "litoken"
    linkedin_version = "202507"
    google_client_id = "client"
    google_client_secret = "secret"
    google_refresh_token = "refresh"

    def facebook_page(self, page_id):
        return next((row for row in self.facebook_pages if row["id"] == page_id), None)

    def platform_ready(self, key):
        if key.startswith("facebook:"):
            return self.facebook_page(key.split(":", 1)[1]) is not None
        if key == "threads":
            return bool(self.threads_user_id and self.threads_token)
        if key == "linkedin":
            return bool(self.linkedin_author_urn and self.linkedin_token)
        if key == "telegram":
            return bool(self.telegram_bot_token and self.telegram_chat_id)
        if key == "instagram":
            return bool(self.instagram_user_id and self.instagram_token)
        return False


class FakePublisher:
    def __init__(self, *, remote_id="42", error: Exception | None = None, wait_event=None):
        self.remote_id = remote_id
        self.error = error
        self.wait_event = wait_event

    def publish(self, text, progress, context, media=None):
        context.before_write()
        if self.wait_event is not None:
            self.wait_event.wait(timeout=3)
        if self.error is not None:
            raise self.error
        updated = {**progress, "transport": "done"}
        context.save_progress(updated)
        return PublishResult(remote_id=self.remote_id, progress=updated)


def _ctx():
    return PublishContext(before_write=lambda: None, save_progress=lambda _p: None)


def _adapters(config):
    settings = DonationSettings(text="support", targets=[])
    return (
        TelegramAdapter(config, settings),
        InstagramAdapter(config, settings),
        FacebookAdapter(config, settings),
        ThreadsAdapter(config, settings),
        LinkedInAdapter(config, settings),
    )


def test_registry_has_one_adapter_per_supported_platform():
    config = FakeConfig()
    registry = DestinationRegistry(config, _adapters(config))
    assert registry.adapter_for("telegram:-1001").platform == "telegram"
    assert registry.adapter_for("instagram:ig1").platform == "instagram"
    assert registry.adapter_for("facebook:fb1").platform == "facebook"
    assert registry.adapter_for("threads").platform == "threads"
    assert registry.adapter_for("linkedin").platform == "linkedin"
    assert all(adapter.platform != "google_drive" for adapter in registry.adapters)


def test_auth_state_is_separate_from_publish():
    config = FakeConfig()
    adapters = _adapters(config)
    assert adapters[0].auth_status("telegram:-1001").state is AuthState.CONNECTED
    assert adapters[1].auth_status("instagram:ig1").state is AuthState.CONNECTED
    assert adapters[2].auth_status("facebook:fb1").state is AuthState.CONNECTED
    assert adapters[3].auth_status("threads").state is AuthState.CONNECTED
    assert adapters[4].auth_status("linkedin").state is AuthState.CONNECTED


def test_adapter_returns_sent_outcome(monkeypatch):
    config = FakeConfig()
    adapter = TelegramAdapter(config, DonationSettings())
    monkeypatch.setattr(adapter, "create_publisher", lambda _key: FakePublisher(remote_id="777"))
    checkpoint = Checkpoint({})
    result = adapter.publish(PublishPayload("telegram:-1001", "hello"), checkpoint, _ctx())
    assert result.outcome is PublicationOutcome.SENT
    assert result.remote_id == "777"
    assert result.checkpoint["transport"] == "done"


def test_unknown_never_becomes_retryable(monkeypatch):
    config = FakeConfig()
    adapter = ThreadsAdapter(config, DonationSettings())
    monkeypatch.setattr(
        adapter,
        "create_publisher",
        lambda _key: FakePublisher(error=PublishError("ambiguous", retryable=True, outcome_unknown=True)),
    )
    result = adapter.publish(PublishPayload("threads", "hello"), Checkpoint({}), _ctx())
    assert result.outcome is PublicationOutcome.UNKNOWN
    assert result.retryable is False


def test_known_failure_keeps_retry_metadata(monkeypatch):
    config = FakeConfig()
    adapter = LinkedInAdapter(config, DonationSettings())
    monkeypatch.setattr(
        adapter,
        "create_publisher",
        lambda _key: FakePublisher(error=PublishError("rate", retryable=True, rate_limited=True)),
    )
    result = adapter.publish(PublishPayload("linkedin", "hello"), Checkpoint({}), _ctx())
    assert result.outcome is PublicationOutcome.FAILED_KNOWN
    assert result.retryable is True


def test_untyped_exception_fails_closed_as_unknown(monkeypatch):
    config = FakeConfig()
    adapter = FacebookAdapter(config, DonationSettings())
    monkeypatch.setattr(adapter, "create_publisher", lambda _key: FakePublisher(error=OSError("socket vanished")))
    result = adapter.publish(PublishPayload("facebook:fb1", "hello"), Checkpoint({}), _ctx())
    assert result.outcome is PublicationOutcome.UNKNOWN
    assert result.retryable is False


def test_worker_factory_facade_preserves_legacy_publisher_api(monkeypatch):
    service = PublishingService(FakeConfig(), DonationSettings())
    adapter = service.registry.adapter_for("telegram:-1001")
    monkeypatch.setattr(adapter, "create_publisher", lambda _key: FakePublisher(remote_id="888"))
    factory = PlatformPublisherFactory(service)
    result = factory.create("telegram:-1001").publish("text", {}, _ctx())
    assert result.remote_id == "888"


def test_graceful_shutdown_blocks_new_writes_and_waits_for_inflight(monkeypatch):
    service = PublishingService(FakeConfig(), DonationSettings())
    adapter = service.registry.adapter_for("threads")
    release = threading.Event()
    monkeypatch.setattr(adapter, "create_publisher", lambda _key: FakePublisher(wait_event=release))

    holder = []
    thread = threading.Thread(
        target=lambda: holder.append(service.publish(PublishPayload("threads", "one"), Checkpoint({}), _ctx())),
        daemon=True,
    )
    thread.start()
    for _ in range(100):
        if service.inflight:
            break
        time.sleep(0.01)
    assert service.inflight == 1
    service.begin_shutdown()
    blocked = service.publish(PublishPayload("threads", "two"), Checkpoint({}), _ctx())
    assert blocked.outcome is PublicationOutcome.NOT_ATTEMPTED
    assert service.wait_for_safe_boundary(0.01) is False
    release.set()
    thread.join(timeout=2)
    assert service.wait_for_safe_boundary(1.0) is True
    assert holder[0].outcome is PublicationOutcome.SENT


def test_drive_is_media_service_not_destination_adapter():
    config = FakeConfig()
    service = PublishingService(config, DonationSettings())
    media = GoogleDriveMediaService(config)
    assert media.platform == "google_drive"
    assert all(adapter.platform != "google_drive" for adapter in service.registry.adapters)


def test_app_services_composes_publishing_and_media():
    fake_db = SimpleNamespace()
    services = build_services(config=FakeConfig(), database=fake_db)
    assert services.publishing.registry.adapter_for("threads").platform == "threads"
    assert isinstance(services.media, GoogleDriveMediaService)
