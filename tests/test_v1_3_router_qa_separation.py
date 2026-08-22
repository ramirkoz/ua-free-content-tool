from __future__ import annotations

from types import SimpleNamespace

import content_agent.ai_provider_diagnostics_v1_2_1 as diagnostics
import content_agent.ai_router_v1_2_1 as legacy_router
import content_agent.local_ai_runtime_v1_2_2 as local_runtime
import content_agent.rewrite_pipeline_v1_3 as rewrite_pipeline
from content_agent.fact_guard import FactGuardResult


def test_provider_health_accepts_non_literal_nonempty_response(monkeypatch):
    slot = legacy_router.AIModelSlot(1, "nvidia", "model-a", "NVIDIA A", "openai")
    monkeypatch.setattr(diagnostics, "_provider_slot_groups", lambda: [("nvidia", [slot])])
    monkeypatch.setattr(diagnostics, "load_provider_secrets", lambda: SimpleNamespace())
    monkeypatch.setattr(diagnostics, "_configured", lambda _slot, _cfg: True)
    monkeypatch.setattr(diagnostics, "_invoke_limited", lambda *_args, **_kwargs: "different but healthy response")

    row = diagnostics.test_configured_providers()[0]
    assert row.status == "ok"
    assert "відповідь отримано" in row.detail


def test_router_health_accepts_non_literal_nonempty_response(monkeypatch):
    monkeypatch.setattr(
        legacy_router,
        "run_ai",
        lambda *_args, **_kwargs: legacy_router.AIResult("anything", "nvidia", "m", "NVIDIA", 1, ()),
    )
    assert "AI Router працює" in legacy_router.test_ai_router()


def test_local_health_accepts_non_literal_response(monkeypatch):
    monkeypatch.setattr(
        local_runtime,
        "generate_local_text",
        lambda **_kwargs: ("healthy local reply", SimpleNamespace(label="qwen/Ollama", model="qwen")),
    )
    target = local_runtime.test_local_runtime()
    assert target.model == "qwen"


def test_qwen_think_wrapper_is_removed_before_parse():
    cleaned = rewrite_pipeline._clean_json_text(
        "<think>internal notes</think>\n"
        "ЗАГОЛОВОК: Тест\n"
        "ТЕКСТ: Повний український текст новини після службового блоку."
    )
    assert "<think>" not in cleaned
    assert cleaned.startswith("ЗАГОЛОВОК:")


def test_post_ai_qa_retries_only_rejected_model(monkeypatch):
    routes = [
        legacy_router.AIResult("bad", "nvidia", "m1", "NVIDIA m1", 1, ()),
        legacy_router.AIResult("good", "nvidia", "m2", "NVIDIA m2", 2, ()),
    ]
    calls: list[dict[str, object]] = []

    def fake_router(_prompt, _local_prompt, **kwargs):
        calls.append(kwargs)
        return routes.pop(0)

    def fake_candidate(route, _evidence, *, language):
        del language
        if route.text == "bad":
            raise rewrite_pipeline.AIRouterError("bad structure")
        return rewrite_pipeline.RewriteCandidate(
            "headline", "body", "", route, FactGuardResult(True, (), 92)
        )

    monkeypatch.setattr(rewrite_pipeline, "_router_call", fake_router)
    monkeypatch.setattr(rewrite_pipeline, "_candidate", fake_candidate)
    evidence = SimpleNamespace(
        text="source",
        source_count=1,
        selected_sentences=1,
        total_sentences=1,
        truncated=False,
    )

    candidate = rewrite_pipeline._candidate_after_router("cloud", "local", evidence, language="uk")
    assert candidate.route.model == "m2"
    assert "m1" in calls[1]["skip_models"]


def test_fact_guard_rejection_retries_without_health_failure(monkeypatch):
    routes = [
        legacy_router.AIResult("first", "nvidia", "m1", "NVIDIA m1", 1, ()),
        legacy_router.AIResult("second", "groq", "m2", "Groq m2", 2, ()),
    ]
    monkeypatch.setattr(rewrite_pipeline, "_router_call", lambda *_args, **_kwargs: routes.pop(0))

    def fake_candidate(route, _evidence, *, language):
        del language
        if route.text == "first":
            return rewrite_pipeline.RewriteCandidate(
                "headline", "bad", "", route, FactGuardResult(False, ("invented entity",), 25)
            )
        return rewrite_pipeline.RewriteCandidate(
            "headline", "good", "", route, FactGuardResult(True, (), 95)
        )

    monkeypatch.setattr(rewrite_pipeline, "_candidate", fake_candidate)
    evidence = SimpleNamespace(
        text="source",
        source_count=1,
        selected_sentences=1,
        total_sentences=1,
        truncated=False,
    )

    candidate = rewrite_pipeline._candidate_after_router("cloud", "local", evidence, language="uk")
    assert candidate.route.provider == "groq"
