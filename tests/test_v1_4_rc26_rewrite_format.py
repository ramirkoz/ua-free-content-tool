from __future__ import annotations

from content_agent.ai_router_v1_2_1 import AIResult
from content_agent.evidence_pack import EvidencePack
from content_agent.models import Article, NewsGroup
from content_agent import rewrite_pipeline_v1_3 as base
from content_agent import rewrite_pipeline_v1_4_rc26 as rc26


def _group() -> NewsGroup:
    article = Article(
        id=1,
        source_id=1,
        title="У місті відкрили новий центр",
        url="https://example.com/news",
        raw_text="У місті відкрили новий центр допомоги. Він працюватиме щодня.",
        status="new",
        published_at="2026-09-07T10:00:00+00:00",
        source_name="Example",
    )
    return NewsGroup(
        id=1,
        canonical_title=article.title,
        status="new",
        created_at="2026-09-07T10:00:00+00:00",
        updated_at="2026-09-07T10:00:00+00:00",
        source_count=1,
        articles=[article],
    )


def test_rc26_recovers_truncated_json_envelope() -> None:
    raw = (
        '{"headline":"У місті відкрили новий центр",'
        '"rewrite":"У місті відкрили новий центр допомоги. Він працюватиме щодня."'
    )
    payload = rc26.decode_payload_rc26(raw)
    assert payload["headline"] == "У місті відкрили новий центр"
    assert payload["rewrite"] == "У місті відкрили новий центр допомоги. Він працюватиме щодня."


def test_rc26_accepts_markdown_decorated_marker_protocol() -> None:
    raw = (
        "**ЗАГОЛОВОК:** У місті відкрили новий центр\n"
        "**ТЕКСТ:** У місті відкрили новий центр допомоги. Він працюватиме щодня."
    )
    payload = rc26.decode_payload_rc26(raw)
    assert payload["headline"] == "У місті відкрили новий центр"
    assert str(payload["rewrite"]).startswith("У місті відкрили")


def test_rc26_accepts_single_object_json_array() -> None:
    raw = '[{"title":"У місті відкрили новий центр","text":"У місті відкрили новий центр допомоги. Він працюватиме щодня."}]'
    payload = rc26.decode_payload_rc26(raw)
    assert payload["headline"] == "У місті відкрили новий центр"
    assert "працюватиме щодня" in str(payload["rewrite"])


def test_rc26_cloud_prompt_uses_marker_protocol_not_json() -> None:
    evidence = EvidencePack(
        text="У місті відкрили новий центр допомоги. Він працюватиме щодня.",
        source_count=1,
        selected_sentences=2,
        total_sentences=2,
        truncated=False,
    )
    prompt = rc26.cloud_prompt_rc26(_group(), evidence, [], "", language="uk")
    assert "ЗАГОЛОВОК:" in prompt
    assert "ТЕКСТ:" in prompt
    assert "JSON-об'єкт" not in prompt


def test_rc26_allows_one_format_repair_for_groq(monkeypatch) -> None:
    calls: list[str] = []

    def fake_router_call(prompt: str, local_prompt: str, **kwargs: object) -> AIResult:
        del local_prompt, kwargs
        calls.append(prompt)
        if "FORMAT REPAIR ONLY" in prompt:
            return AIResult(
                "ЗАГОЛОВОК: У місті відкрили новий центр\n"
                "ТЕКСТ: У місті відкрили новий центр допомоги. Він працюватиме щодня.",
                "groq",
                "openai/gpt-oss-120b",
                "GPT-OSS 120B / Groq",
                5,
                ("GPT-OSS 120B / Groq",),
            )
        return AIResult("[]", "groq", "openai/gpt-oss-120b", "GPT-OSS 120B / Groq", 5, ("GPT-OSS 120B / Groq",))

    monkeypatch.setattr(base, "_router_call", fake_router_call)
    evidence = EvidencePack(
        text="У місті відкрили новий центр допомоги. Він працюватиме щодня.",
        source_count=1,
        selected_sentences=2,
        total_sentences=2,
        truncated=False,
    )
    candidate = rc26.candidate_after_router_rc26("PROMPT", "LOCAL", evidence, language="uk", max_candidates=2)
    assert candidate.guard.allowed is True
    assert len(calls) == 2
    assert "FORMAT REPAIR ONLY" in calls[1]
