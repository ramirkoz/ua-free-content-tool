from __future__ import annotations

import pytest

from content_agent import linkedin_comments_v1_2_rc3 as linkedin_comments
from content_agent.linkedin_comments_v1_2_rc3 import CommentedLinkedInPublisher
from content_agent.publishers import PublishContext, PublishError, PublishResult
from content_agent.safe_publishers_v1_2 import SafeLinkedInPublisher


def _context(saved: list[dict[str, object]]) -> PublishContext:
    return PublishContext(
        before_write=lambda: None,
        save_progress=lambda progress: saved.append(dict(progress)),
    )


def _confirmed_main_progress() -> dict[str, object]:
    return {
        "linkedin_post_id": "urn:li:share:123456",
    }


def _return_existing_main(self, text, progress, context, media=None):
    return PublishResult(remote_id="urn:li:share:123456", progress=dict(progress))


def test_explicit_comment_api_error_preserves_detail_and_allows_safe_retry(monkeypatch) -> None:
    saved: list[dict[str, object]] = []
    publisher = CommentedLinkedInPublisher("urn:li:person:42", "token", "202607")
    monkeypatch.setattr(SafeLinkedInPublisher, "publish", _return_existing_main)

    def reject_comment(*args, **kwargs):
        raise PublishError(
            "ACCESS_DENIED: Not enough permissions to access comments",
            code=403,
            retryable=False,
            auth_error=True,
        )

    monkeypatch.setattr(linkedin_comments, "_linkedin_post_json", reject_comment)

    with pytest.raises(PublishError) as raised:
        publisher.publish("Новина", _confirmed_main_progress(), _context(saved))

    exc = raised.value
    assert "ACCESS_DENIED" in str(exc)
    assert "донатний коментар" in str(exc)
    assert exc.code == 403
    assert exc.auth_error is True
    assert exc.outcome_unknown is False
    assert saved[-1]["linkedin_donation_comment_started"] is False


def test_ambiguous_comment_failure_is_local_and_does_not_abort_telegram(monkeypatch) -> None:
    saved: list[dict[str, object]] = []
    publisher = CommentedLinkedInPublisher("urn:li:person:42", "token", "202607")
    monkeypatch.setattr(SafeLinkedInPublisher, "publish", _return_existing_main)

    def ambiguous_comment(*args, **kwargs):
        raise RuntimeError("connection closed after write")

    monkeypatch.setattr(linkedin_comments, "_linkedin_post_json", ambiguous_comment)

    with pytest.raises(PublishError) as raised:
        publisher.publish("Новина", _confirmed_main_progress(), _context(saved))

    exc = raised.value
    assert "результат етапу «донатний коментар» невідомий" in str(exc)
    assert exc.retryable is False
    assert exc.outcome_unknown is False
    assert saved[-1]["linkedin_donation_comment_started"] is True
    assert saved[-1]["linkedin_donation_comment_completed"] is False


def test_unresolved_comment_marker_never_reposts_linkedin_and_is_target_local(monkeypatch) -> None:
    publisher = CommentedLinkedInPublisher("urn:li:person:42", "token", "202607")
    monkeypatch.setattr(SafeLinkedInPublisher, "publish", _return_existing_main)
    progress = {
        **_confirmed_main_progress(),
        "linkedin_donation_comment_started": True,
        "linkedin_donation_comment_completed": False,
    }
    called = False

    def should_not_call(*args, **kwargs):
        nonlocal called
        called = True
        return {}, {"x-restli-id": "unexpected"}

    monkeypatch.setattr(linkedin_comments, "_linkedin_post_json", should_not_call)

    with pytest.raises(PublishError) as raised:
        publisher.publish("Новина", progress, _context([]))

    assert called is False
    assert raised.value.retryable is False
    assert raised.value.outcome_unknown is False
    assert "донатний коментар" in str(raised.value)


def test_successful_comment_returns_root_post_id(monkeypatch) -> None:
    saved: list[dict[str, object]] = []
    publisher = CommentedLinkedInPublisher("urn:li:person:42", "token", "202607")
    monkeypatch.setattr(SafeLinkedInPublisher, "publish", _return_existing_main)

    def publish_comment(*args, **kwargs):
        return {"id": "comment-789"}, {"x-restli-id": "comment-789"}

    monkeypatch.setattr(linkedin_comments, "_linkedin_post_json", publish_comment)

    result = publisher.publish("Новина", _confirmed_main_progress(), _context(saved))

    assert result.remote_id == "urn:li:share:123456"
    assert result.progress["linkedin_donation_comment_id"] == "comment-789"
    assert result.progress["linkedin_donation_comment_completed"] is True
