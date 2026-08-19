from __future__ import annotations

from content_agent.ai_router_v1_2_1 import AIResult
from content_agent.evidence_pack import build_evidence_pack
from content_agent.fact_guard import guard_rewrite
from content_agent.models import Article, NewsGroup
import content_agent.rewrite_pipeline_v1_3 as pipeline


def _group(text: str) -> NewsGroup:
    article = Article(
        id=1,
        source_id=1,
        title="Meta Muse Glimmer",
        url="https://example.com/meta",
        raw_text=text,
        status="new",
        published_at="2026-08-18T10:00:00+00:00",
        source_name="Example",
    )
    return NewsGroup(
        id=1,
        canonical_title=article.title,
        status="new",
        created_at="2026-08-18T10:00:00+00:00",
        updated_at="2026-08-18T10:00:00+00:00",
        source_count=1,
        articles=[article],
    )


def test_evidence_pack_keeps_late_fact_when_lead_is_pathologically_long() -> None:
    lead = "Вступ " + ("дуже довгий " * 180) + "."
    late = "Meta повідомила, що Muse Glimmer має 8 млрд параметрів і працює на одному GPU."
    pack = build_evidence_pack(_group(lead + " " + late), max_chars=900)
    assert len(pack.text) <= 900
    assert "8 млрд" in pack.text
    assert "Muse Glimmer" in pack.text
    assert pack.truncated is True


def test_fact_guard_blocks_invented_year_and_model() -> None:
    evidence = "Meta представила Muse Glimmer 18 серпня 2026 року."
    result = guard_rewrite(
        evidence,
        "Meta представила ModelX",
        "Meta представила ModelX у 2024 році.",
        language="uk",
    )
    assert result.allowed is False
    assert "2024" in result.unsupported_numbers
    assert "modelx" in result.unsupported_entities


def test_fact_guard_blocks_unsupported_superlative_but_not_ordinary_first_quarter() -> None:
    bad = guard_rewrite(
        "Компанія представила нову систему.",
        "Нова система",
        "Це найбільша система у світі.",
    )
    assert bad.allowed is False

    good = guard_rewrite(
        "У першому кварталі компанія збільшила виручку на 12%.",
        "Результати першого кварталу",
        "У першому кварталі виручка зросла на 12%.",
    )
    assert good.allowed is True


def test_v13_adaptive_rewrite_uses_next_model_after_fact_guard_reject(monkeypatch) -> None:
    calls: list[set[str]] = []

    def fake_run_ai(prompt: str, **kwargs):
        del prompt
        skip = set(kwargs.get("skip_models") or ())
        calls.append(skip)
        if "nvidia-m1" in skip:
            text = '{"headline":"Meta представила Muse Glimmer","fact_card":"","rewrite":"Meta представила Muse Glimmer з 8 млрд параметрів."}'
            model = "nvidia-m2"
            label = "NVIDIA test 2"
        else:
            text = '{"headline":"Meta представила ModelX","fact_card":"","rewrite":"Meta представила ModelX у 2024 році з 8 млрд параметрів."}'
            model = "nvidia-m1"
            label = "NVIDIA test 1"
        validator = kwargs.get("validator")
        if validator is not None:
            validator(text)
        return AIResult(text, "nvidia", model, label, 1, (label,))

    monkeypatch.setattr(pipeline, "run_ai", fake_run_ai)
    group = _group("Meta представила Muse Glimmer з 8 млрд параметрів.")
    result = pipeline.rewrite_group_v13(group, [], language="uk")

    assert result.headline == "Meta представила Muse Glimmer"
    assert "2024" not in result.rewrite
    assert calls == [set(), {"nvidia-m1"}]
    assert pipeline.last_rewrite_engine_label() == "NVIDIA test 2"
    assert "Fact Guard PASS" in pipeline.last_rewrite_diagnostic()
