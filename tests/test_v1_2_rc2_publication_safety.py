from __future__ import annotations

import pytest

from content_agent.network import HttpResponse, NetworkError
from content_agent.publishers import PublishContext, PublishError, ThreadsPublisher
from content_agent.safe_publishers_v1_2 import (
    SafeLinkedInPublisher,
    SafeThreadsPublisher,
    _linkedin_post_json,
)


def test_linkedin_json_accepts_empty_success_without_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(*args: object, **kwargs: object) -> HttpResponse:
        return HttpResponse(
            status=201,
            headers={"x-restli-id": "urn:li:share:123"},
            body=b"",
            final_url="https://api.linkedin.com/rest/posts",
        )

    monkeypatch.setattr("content_agent.safe_publishers_v1_2.fetch_url", fake_fetch)
    payload, headers = _linkedin_post_json(
        "https://api.linkedin.com/rest/posts",
        {"commentary": "text"},
        {"Authorization": "Bearer token"},
    )
    assert payload == {}
    assert headers["x-restli-id"] == "urn:li:share:123"


def test_linkedin_success_progress_prevents_second_create_post(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_post(*args: object, **kwargs: object) -> tuple[dict[str, object], dict[str, str]]:
        nonlocal calls
        calls += 1
        return {}, {"x-restli-id": "urn:li:share:created"}

    monkeypatch.setattr("content_agent.safe_publishers_v1_2._linkedin_post_json", fake_post)
    publisher = SafeLinkedInPublisher("urn:li:person:abc", "token", "202601")
    saved: list[dict[str, object]] = []
    context = PublishContext(before_write=lambda: None, save_progress=lambda value: saved.append(dict(value)))

    first = publisher.publish("same text", {}, context)
    assert first.remote_id == "urn:li:share:created"
    assert calls == 1
    assert saved[-1]["linkedin_write_completed"] is True
    assert saved[-1]["linkedin_post_id"] == "urn:li:share:created"

    second = publisher.publish("same text", dict(saved[-1]), context)
    assert second.remote_id == "urn:li:share:created"
    assert calls == 1, "a completed LinkedIn write must never POST a second time"


def test_linkedin_ambiguous_write_is_blocked_on_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def failing_post(*args: object, **kwargs: object) -> tuple[dict[str, object], dict[str, str]]:
        nonlocal calls
        calls += 1
        raise NetworkError("connection closed after request write")

    monkeypatch.setattr("content_agent.safe_publishers_v1_2._linkedin_post_json", failing_post)
    publisher = SafeLinkedInPublisher("urn:li:person:abc", "token", "202601")
    saved: list[dict[str, object]] = []
    context = PublishContext(before_write=lambda: None, save_progress=lambda value: saved.append(dict(value)))

    with pytest.raises(PublishError) as first_error:
        publisher.publish("same text", {}, context)
    assert first_error.value.outcome_unknown is True
    assert first_error.value.retryable is False
    assert calls == 1
    assert saved[-1]["linkedin_write_started"] is True
    assert saved[-1]["linkedin_write_completed"] is False

    with pytest.raises(PublishError) as second_error:
        publisher.publish("same text", dict(saved[-1]), context)
    assert second_error.value.outcome_unknown is True
    assert calls == 1, "ambiguous LinkedIn outcome must not issue another create POST"


def test_threads_unknown_becomes_descriptive_nonretryable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def base_publish(*args: object, **kwargs: object):
        raise PublishError("UNKNOWN")

    monkeypatch.setattr(ThreadsPublisher, "publish", base_publish)
    publisher = SafeThreadsPublisher("user", "token")
    context = PublishContext(before_write=lambda: None, save_progress=lambda _value: None)

    with pytest.raises(PublishError) as error:
        publisher.publish("text", {}, context)
    assert error.value.retryable is False
    assert "UNKNOWN" in str(error.value)
    assert "Автоматичний повтор зупинено" in str(error.value)
