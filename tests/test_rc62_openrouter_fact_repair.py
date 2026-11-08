"""RC62 regression: OpenRouter should get a single guarded factual repair, never a QA bypass."""
from __future__ import annotations

import time

import pytest

from content_agent.ai_router import AIRouterError
from content_agent.ai_router_v1_2_1 import AIResult
from content_agent.evidence_pack import EvidencePack
from content_agent import rewrite_pipeline_v1_3 as base
from content_agent import rewrite_pipeline_v1_4_rc17 as rc17
from content_agent import rewrite_pipeline_v1_4_rc27 as rc27


EVIDENCE_TEXT = (
    "Громада отримала 3 автобуси для перевезення мешканців. "
    "Автобуси передали комунальному підприємству для щоденних маршрутів."
)


def _evidence() -> EvidencePack:
    return EvidencePack(
        text=EVIDENCE_TEXT,
        source_count=1,
        selected_sentences=2,
        total_sentences=2,
        truncated=False,
    )


def _route(amount: int) -> AIResult:
    public = (
        f"Громада отримала {amount} автобуси для перевезення мешканців. "
        "Автобуси передали комунальному підприємству для щоденних маршрутів."
    )
    # Both attempts use the exact same public envelope.
    return AIResult(
        '{"headline":"Громада отримала автобуси","fact_card":"","rewrite":'
        + __import__("json").dumps(public, ensure_ascii=False) + "}",
        "openrouter",
        "x-ai/grok-4.20",
        "Grok 4.20 / OpenRouter",
        0,
        ("Grok 4.20 / OpenRouter",),
    )


def test_rc62_openrouter_fact_repair_is_one_shot_and_still_qa_gated(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_ai(prompt: str, local_prompt: str, **kwargs: object) -> AIResult:
        del local_prompt
        calls.append({"prompt": prompt, **kwargs})
        return _route(3 if "FACT-SAFE REPAIR" in prompt else 4)

    monkeypatch.setattr(base, "_router_call", fake_ai)
    monkeypatch.setattr(base, "_decode_payload", rc27.decode_payload_rc27)
    candidate = rc27.candidate_after_router_rc27(
        "Напиши рерайт за наведеними фактами", "LOCAL", _evidence(),
        language="uk", max_candidates=2, deadline=time.monotonic() + 80,
    )
    assert candidate.guard.allowed is True
    assert "3 автобуси" in candidate.rewrite
    assert "4 автобуси" not in candidate.rewrite
    assert len(calls) == 2
    assert "FACT-SAFE REPAIR" in str(calls[1]["prompt"])
    assert "openrouter" in rc17._FACT_REPAIR_PROVIDERS
    assert "openrouter" not in calls[1]["skip_providers"]
    assert "groq" in calls[1]["skip_providers"]


def test_rc62_openrouter_fact_repair_still_rejects_unsupported_claim(monkeypatch) -> None:
    calls: list[str] = []

    def fake_ai(prompt: str, local_prompt: str, **kwargs: object) -> AIResult:
        del local_prompt, kwargs
        calls.append(prompt)
        return _route(4)

    monkeypatch.setattr(base, "_router_call", fake_ai)
    monkeypatch.setattr(base, "_decode_payload", rc27.decode_payload_rc27)
    with pytest.raises(AIRouterError, match="post-AI QA"):
        rc27.candidate_after_router_rc27(
            "Напиши рерайт за наведеними фактами", "LOCAL", _evidence(),
            language="uk", max_candidates=1, deadline=time.monotonic() + 80,
        )
    # Two fresh attempts plus exactly one correction, never unbounded repairs.
    assert len(calls) == 3
    assert len([x for x in calls if "FACT-SAFE REPAIR" in x]) == 1
