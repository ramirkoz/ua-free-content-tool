from __future__ import annotations

from content_agent.comment_compat_v1_2_rc3 import _with_inline_fund_footer
from content_agent.instagram_target_v1_2_rc4 import _instagram_caption
from content_agent.publication_policy_v1_2_rc3 import compose_publication_text_rc3
from content_agent.publication_policy_v1_2_rc4 import compose_publication_text_rc4
from content_agent.publication_text import FUND_FOOTER


def test_final_donation_placement_policy() -> None:
    core = "Тестова новина"
    source = "https://example.com/news"

    facebook = compose_publication_text_rc4(core, "facebook", include_source_link=True, source_url=source)
    threads = compose_publication_text_rc4(core, "threads", include_source_link=True, source_url=source)
    linkedin = compose_publication_text_rc4(core, "linkedin", include_source_link=True, source_url=source)
    telegram = compose_publication_text_rc4(core, "telegram", include_source_link=True, source_url=source)
    instagram = compose_publication_text_rc4(core, "instagram", include_source_link=True, source_url=source)

    assert FUND_FOOTER not in facebook
    assert FUND_FOOTER not in threads
    for text in (linkedin, telegram, instagram):
        assert text.count(FUND_FOOTER) == 1
        assert text.index(FUND_FOOTER) < text.index("Джерело:")


def test_linkedin_publish_compat_upgrades_old_queued_payload() -> None:
    old = "Тестова новина\n\nДжерело: https://example.com/news"
    upgraded = _with_inline_fund_footer(old)
    assert upgraded == f"Тестова новина\n\n{FUND_FOOTER}\n\nДжерело: https://example.com/news"
    assert _with_inline_fund_footer(upgraded) == upgraded


def test_instagram_caption_upgrades_old_queued_payload() -> None:
    old = "Тестова новина\n\nДжерело: https://example.com/news"
    upgraded = _instagram_caption(old)
    assert upgraded == f"Тестова новина\n\n{FUND_FOOTER}\n\nДжерело: https://example.com/news"
    assert _instagram_caption(upgraded) == upgraded


def test_rc3_policy_keeps_linkedin_and_telegram_inline() -> None:
    for platform in ("linkedin", "telegram"):
        text = compose_publication_text_rc3(
            "Тестова новина",
            platform,
            include_source_link=False,
            source_url="",
        )
        assert text.endswith(FUND_FOOTER)
