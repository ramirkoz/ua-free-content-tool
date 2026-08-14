from __future__ import annotations

import content_agent.facebook_comments_v1_2_rc3 as facebook_comments
import content_agent.publishers as publishers
from content_agent.comment_compat_v1_2_rc3 import CompatibleFacebookPublisher, _without_legacy_footer
from content_agent.publication_policy_v1_2_rc3 import DONATION_COMMENT
from content_agent.publication_text import FUND_FOOTER
from content_agent.publishers import PublishContext, PublishResult


def test_legacy_facebook_payload_is_normalized_not_bypassed(monkeypatch) -> None:
    main_texts: list[str] = []
    comment_calls: list[tuple[str, dict[str, object]]] = []
    saved: list[dict[str, object]] = []

    def fake_main(self, text, progress, context, media=None):  # noqa: ANN001
        main_texts.append(text)
        return PublishResult(remote_id="page_1_post_77", progress={})

    def fake_comment(url: str, fields: dict[str, object], *, timeout: float = 45):
        del timeout
        comment_calls.append((url, fields))
        return {"id": "comment_88"}

    monkeypatch.setattr(publishers.FacebookPagePublisher, "publish", fake_main)
    monkeypatch.setattr(facebook_comments, "_post_form", fake_comment)

    publisher = CompatibleFacebookPublisher("page_1", "token", "v26.0")
    context = PublishContext(before_write=lambda: None, save_progress=lambda value: saved.append(dict(value)))
    legacy = f"Тестова новина\n\n{FUND_FOOTER}\n\nДжерело: https://example.test/news"

    result = publisher.publish(legacy, {}, context)

    assert main_texts == ["Тестова новина\n\nДжерело: https://example.test/news"]
    assert len(comment_calls) == 1
    assert comment_calls[0][0].endswith("/page_1_post_77/comments")
    assert comment_calls[0][1]["message"] == DONATION_COMMENT
    assert result.remote_id == "page_1_post_77"
    assert result.progress["facebook_donation_comment_completed"] is True
    assert result.progress["facebook_donation_comment_id"] == "comment_88"
    assert any(item.get("facebook_donation_main_completed") is True for item in saved)
    assert any(item.get("facebook_donation_comment_started") is True for item in saved)
    assert any(item.get("facebook_donation_comment_completed") is True for item in saved)


def test_footer_normalizer_preserves_clean_payload_and_source() -> None:
    clean = "Коротка новина\n\nДжерело: https://example.test/a"
    assert _without_legacy_footer(clean, "facebook") == clean
    legacy = f"Коротка новина\n\n{FUND_FOOTER}\n\nДжерело: https://example.test/a"
    assert _without_legacy_footer(legacy, "facebook") == clean
