from content_agent.publication_policy_v1_2_rc3 import compose_publication_text_rc3
from content_agent.publication_text import FUND_FOOTER


def test_telegram_keeps_footer() -> None:
    text = compose_publication_text_rc3("News", "telegram", include_source_link=False, source_url="")
    assert FUND_FOOTER in text


def test_social_root_posts_do_not_include_footer() -> None:
    for platform in ("facebook", "threads", "linkedin", "instagram"):
        text = compose_publication_text_rc3("News", platform, include_source_link=False, source_url="")
        assert FUND_FOOTER not in text
