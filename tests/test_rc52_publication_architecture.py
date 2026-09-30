from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from content_agent.app.container import build_services
from content_agent.config import AppConfig
from content_agent.publishers import PublishError, PublishResult, Publisher
from content_agent.v2.publishing.adapters import PublisherPlatformAdapter, TELEGRAM_CAPABILITIES
from content_agent.v2.publishing.contracts import AuthState, AuthStatus, PublishPayload
from content_agent.v2.publishing.outcomes import PublicationOutcome
from content_agent.v2.publishing.registry import DestinationError, DestinationRegistry
from content_agent.v2.publishing.service import PublicationService


class _Publisher(Publisher):
    def __init__(self, *, fail: Exception | None = None, delay: float = 0.0):
        self.fail = fail
        self.delay = delay

    def publish(self, text, progress, context, media=None):
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise self.fail
        context.before_write()
        updated = {**progress, "done": True}
        context.save_progress(updated)
        return PublishResult(remote_id="remote-1", progress=updated)


def _adapter(*, fail=None, delay=0.0, auth=AuthState.CONNECTED):
    return PublisherPlatformAdapter(
        "telegram",
        lambda _destination, _payload: _Publisher(fail=fail, delay=delay),
        TELEGRAM_CAPABILITIES,
        lambda _destination: AuthStatus(auth, auth.value),
    )


def test_registry_resolves_dynamic_platform_destination_and_rejects_drive():
    registry = DestinationRegistry([_adapter()])
    assert registry.resolve("telegram:-100123").family == "telegram"
    assert registry.families() == ("telegram",)
    with pytest.raises(DestinationError):
        registry.resolve("google_drive")
    with pytest.raises(ValueError):
        class _Drive:
            family = "google_drive"
        registry.register(_Drive())


def test_known_failure_may_retry_but_unknown_never_auto_retries():
    known = PublicationService(DestinationRegistry([_adapter(fail=PublishError("rate", retryable=True))]))
    attempt = known.publish("telegram:x", PublishPayload("hello"))
    assert attempt.outcome is PublicationOutcome.FAILED_KNOWN
    assert known.can_automatically_retry(attempt) is True

    unknown = PublicationService(
        DestinationRegistry([_adapter(fail=PublishError("ambiguous", retryable=True, outcome_unknown=True))])
    )
    attempt = unknown.publish("telegram:x", PublishPayload("hello"))
    assert attempt.outcome is PublicationOutcome.UNKNOWN
    assert attempt.retryable is False
    assert unknown.can_automatically_retry(attempt) is False


def test_auth_failure_is_known_and_not_retried():
    service = PublicationService(DestinationRegistry([_adapter(auth=AuthState.EXPIRED)]))
    attempt = service.publish("telegram:x", PublishPayload("hello"))
    assert attempt.outcome is PublicationOutcome.FAILED_KNOWN
    assert attempt.auth_error is True
    assert service.can_automatically_retry(attempt) is False


def test_success_maps_remote_id_and_progress():
    saved = []
    service = PublicationService(DestinationRegistry([_adapter()]))
    attempt = service.publish(
        "telegram:x",
        PublishPayload("hello"),
        progress={"start": True},
        save_progress=lambda value: saved.append(value),
    )
    assert attempt.outcome is PublicationOutcome.SENT
    assert attempt.remote_id == "remote-1"
    assert attempt.progress["done"] is True
    assert saved[-1]["done"] is True


def test_graceful_close_waits_for_in_flight_and_blocks_new_work():
    service = PublicationService(DestinationRegistry([_adapter(delay=0.12)]))
    result = []
    thread = threading.Thread(target=lambda: result.append(service.publish("telegram:x", PublishPayload("one"))))
    thread.start()
    deadline = time.monotonic() + 1.0
    while service.in_flight == 0 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert service.in_flight == 1
    assert service.close(timeout=1.0) is True
    thread.join(timeout=1.0)
    assert result[0].outcome is PublicationOutcome.SENT
    blocked = service.publish("telegram:x", PublishPayload("two"))
    assert blocked.outcome is PublicationOutcome.NOT_ATTEMPTED


def test_appservices_composes_platform_registry_publication_and_drive_media(monkeypatch, tmp_path):
    monkeypatch.setenv("UA_FREE_DATA_DIR", str(tmp_path))
    services = build_services(config=AppConfig())
    assert services.publishing.registry is services.destinations
    assert set(services.destinations.families()) == {"facebook", "instagram", "linkedin", "telegram", "threads"}
    assert services.media not in services.destinations.adapters()
    with pytest.raises(DestinationError):
        services.destinations.resolve("google_drive")


def test_no_rc52_window_layer_and_no_v2_donation_global_mutation():
    root = Path(__file__).resolve().parents[1] / "content_agent"
    assert not list(root.rglob("*rc52*window*.py"))
    publishing = root / "v2" / "publishing"
    text = "\n".join(path.read_text(encoding="utf-8") for path in publishing.glob("*.py"))
    assert "DONATION_COMMENT =" not in text
    assert "FUND_FOOTER =" not in text
    assert "THREADS_FUND_FOOTER =" not in text
