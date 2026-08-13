from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from content_agent.config import AppConfig
from content_agent.ollama_client import OllamaError
from content_agent.publication_policy_v1_2_rc3 import compose_publication_text_rc3
from content_agent.publication_text import FUND_FOOTER
from content_agent.short_source_v1_2_rc3 import source_values_rc3
from content_agent.strict_ollama_decode_v1_2_rc3 import decode_rewrite_payload_rc3
from content_agent.topic_search import parse_topic_matches
from content_agent.topic_search_v1_2_rc3 import build_topic_prompt_rc3


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    telegram = compose_publication_text_rc3("News", "telegram", include_source_link=False, source_url="")
    check(FUND_FOOTER in telegram, "Telegram fundraiser footer must stay in the message")
    for platform in ("facebook", "threads", "linkedin", "instagram"):
        root = compose_publication_text_rc3("News", platform, include_source_link=False, source_url="")
        check(FUND_FOOTER not in root, f"{platform} root post contains fundraiser footer")

    try:
        decode_rewrite_payload_rc3("HEADLINE: Event\nFACTS: verified\nFinished material")
    except OllamaError:
        pass
    else:
        raise AssertionError("Strict decoder accepted service sections as publication prose")

    decoded = decode_rewrite_payload_rc3("HEADLINE: Event\nFACTS: verified\nTEXT:\nA concise publication sentence.")
    check(decoded.get("rewrite") == "A concise publication sentence.", "Strict decoder leaked protocol sections")

    group = SimpleNamespace(
        canonical_title="Short",
        primary_url="https://example.com/item",
        combined_text="Metadata wrapper",
        include_source_link=False,
        source_count=1,
        articles=[SimpleNamespace(raw_text="One short factual sentence.")],
    )
    check(source_values_rc3(group)[2] == "One short factual sentence.", "Short mode did not use raw article prose")

    prompt = build_topic_prompt_rc3(
        "Opening",
        "A new community space opened.",
        [{"group_id": 7, "title": "Opening", "text": "The community space opened today."}],
        language="en",
    )
    check("ID|SCORE|same_event/related/other|short reason" in prompt, "Topic prompt protocol does not match parser")
    parsed = parse_topic_matches("7|91|same_event|same opening")
    check(7 in parsed and parsed[7].score == 91, "Topic parser protocol validation failed")

    check(not AppConfig().platform_ready("instagram"), "Instagram must remain disabled until connected")
    print("V1_2_RC3_FIELD_FEEDBACK_GATE_OK")


if __name__ == "__main__":
    main()
