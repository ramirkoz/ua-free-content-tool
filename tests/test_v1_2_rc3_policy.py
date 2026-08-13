from types import SimpleNamespace

import pytest

from content_agent.editorial_memory_v1_2_rc3 import hybrid_similarity
from content_agent.ollama_client import OllamaError
from content_agent.publication_policy_v1_2_rc3 import compose_publication_text_rc3
from content_agent.publication_text import FUND_FOOTER
from content_agent.short_source_v1_2_rc3 import source_values_rc3
from content_agent.strict_ollama_decode_v1_2_rc3 import decode_rewrite_payload_rc3
from content_agent.topic_search import parse_topic_matches
from content_agent.topic_search_v1_2_rc3 import build_topic_prompt_rc3


def test_telegram_keeps_footer() -> None:
    text = compose_publication_text_rc3("News", "telegram", include_source_link=False, source_url="")
    assert FUND_FOOTER in text


def test_social_root_posts_do_not_include_footer() -> None:
    for platform in ("facebook", "threads", "linkedin", "instagram"):
        text = compose_publication_text_rc3("News", platform, include_source_link=False, source_url="")
        assert FUND_FOOTER not in text


def test_short_source_uses_raw_article_prose_not_group_wrapper() -> None:
    item = SimpleNamespace(raw_text="A short factual sentence.")
    group = SimpleNamespace(
        canonical_title="Short event",
        primary_url="https://example.com/a",
        combined_text="SOURCE 1: metadata and URL around the actual short text",
        include_source_link=False,
        source_count=1,
        articles=[item],
    )
    _title, _url, source_text, _include, count = source_values_rc3(group)
    assert source_text == "A short factual sentence."
    assert count == 1


def test_strict_decoder_rejects_protocol_sections_without_text_marker() -> None:
    with pytest.raises(OllamaError):
        decode_rewrite_payload_rc3("HEADLINE: Event\nFACTS: verified\nFinished material")


def test_strict_decoder_returns_only_publication_text() -> None:
    result = decode_rewrite_payload_rc3(
        "HEADLINE: Event\nFACTS: verified\nTEXT:\nA new public space opened."
    )
    assert result["rewrite"] == "A new public space opened."


def test_hybrid_similarity_prefers_same_event_wording() -> None:
    close = hybrid_similarity(
        "City rescuers completed work after a severe storm",
        "Rescuers in the city finish recovery work after the storm",
    )
    unrelated = hybrid_similarity(
        "City rescuers completed work after a severe storm",
        "Ministers met to discuss a new finance framework",
    )
    assert close > unrelated


def test_topic_prompt_uses_parser_compatible_protocol() -> None:
    prompt = build_topic_prompt_rc3(
        "Public space",
        "A new public space opened in the city.",
        [{"group_id": 2, "title": "Opening", "text": "The same space opened today."}],
        language="en",
    )
    assert "ID|SCORE|same_event/related/other|short reason" in prompt
    parsed = parse_topic_matches("2|88|same_event|same place and opening")
    assert parsed[2].score == 88
    assert parsed[2].label == "same_event"
