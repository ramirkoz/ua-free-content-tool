from __future__ import annotations

import pytest

from content_agent import facebook_comments_v1_2_rc3 as facebook_comments
from content_agent.facebook_comments_v1_2_rc3 import CommentedFacebookPublisher
from content_agent.publishers import FacebookPagePublisher, PublishContext, PublishError, PublishResult


def _context(saved: list[dict[str, object]]) -> PublishContext:
    return PublishContext(
        before_write=lambda: None,
        save_progress=lambda progress: saved.append(dict(progress)),
    )


def _confirmed_main_progress() -> dict[str, object]:
    return {
        "facebook_donation_main_started": True,
        "facebook_donation_main_completed": True,
        "facebook_donation_main_id": "123_456",
    }


def test_explicit_comment_api_error_preserves_meta_detail_and_allows_safe_retry(monkeypatch) -> None:
    saved: list[dict[str, object]] = []
    publisher = CommentedFacebookPublisher("123", "token", "v24.0")

    def reject_comment(*args, **kwargs):
        raise PublishError(
            "Missing permission for this action",
            code=200,
            retryable=False,
            auth_error=True,
        )

    monkeypatch.setattr(facebook_comments, "_post_form", reject_comment)

    with pytest.raises(PublishError) as raised:
        publisher.publish("Новина", _confirmed_main_progress(), _context(saved))

    exc = raised.value
    assert "Missing permission for this action" in str(exc)
    assert "донатний коментар" in str(exc)
    assert exc.code == 200
    assert exc.auth_error is True
    assert exc.outcome_unknown is False
    assert saved[-1]["facebook_donation_comment_started"] is False


def test_ambiguous_comment_failure_keeps_marker_but_does_not_abort_other_platforms(monkeypatch) -> None:
    saved: list[dict[str, object]] = []
    publisher = CommentedFacebookPublisher("123", "token", "v24.0")

    def ambiguous_comment(*args, **kwargs):
        raise RuntimeError("connection closed after write")

    monkeypatch.setattr(facebook_comments, "_post_form", ambiguous_comment)

    with pytest.raises(PublishError) as raised:
        publisher.publish("Новина", _confirmed_main_progress(), _context(saved))

    exc = raised.value
    assert "результат етапу «донатний коментар» невідомий" in str(exc)
    assert exc.retryable is False
    # Target-local ambiguity is contained by the durable Facebook marker. The
    # worker must therefore continue independent Threads/LinkedIn/Telegram
    # targets instead of breaking the entire package.
    assert exc.outcome_unknown is False
    assert saved[-1]["facebook_donation_comment_started"] is True
    assert saved[-1]["facebook_donation_comment_completed"] is False


def test_unresolved_comment_marker_never_reposts_facebook_and_is_target_local(monkeypatch) -> None:
    publisher = CommentedFacebookPublisher("123", "token", "v24.0")
    progress = {
        **_confirmed_main_progress(),
        "facebook_donation_comment_started": True,
        "facebook_donation_comment_completed": False,
    }
    called = False

    def should_not_call(*args, **kwargs):
        nonlocal called
        called = True
        return {"id": "unexpected"}

    monkeypatch.setattr(facebook_comments, "_post_form", should_not_call)

    with pytest.raises(PublishError) as raised:
        publisher.publish("Новина", progress, _context([]))

    assert called is False
    assert raised.value.retryable is False
    assert raised.value.outcome_unknown is False
    assert "донатний коментар" in str(raised.value)


def test_explicit_main_post_rejection_resets_main_marker(monkeypatch) -> None:
    saved: list[dict[str, object]] = []
    publisher = CommentedFacebookPublisher("123", "token", "v24.0")

    def reject_main(self, text, progress, context, media=None):
        raise PublishError("Facebook rejected root post", code=200, retryable=False, auth_error=True)

    monkeypatch.setattr(FacebookPagePublisher, "publish", reject_main)

    with pytest.raises(PublishError) as raised:
        publisher.publish("Новина", {}, _context(saved))

    assert "Facebook rejected root post" in str(raised.value)
    assert raised.value.outcome_unknown is False
    assert saved[-1]["facebook_donation_main_started"] is False


def test_successful_main_and_comment_return_root_post_id(monkeypatch) -> None:
    saved: list[dict[str, object]] = []
    publisher = CommentedFacebookPublisher("123", "token", "v24.0")

    def publish_main(self, text, progress, context, media=None):
        return PublishResult(remote_id="123_456", progress=progress)

    def publish_comment(*args, **kwargs):
        return {"id": "comment_789"}

    monkeypatch.setattr(FacebookPagePublisher, "publish", publish_main)
    monkeypatch.setattr(facebook_comments, "_post_form", publish_comment)

    result = publisher.publish("Новина", {}, _context(saved))

    assert result.remote_id == "123_456"
    assert result.progress["facebook_donation_main_id"] == "123_456"
    assert result.progress["facebook_donation_comment_id"] == "comment_789"
    assert result.progress["facebook_donation_comment_completed"] is True
