from __future__ import annotations

from content_agent.ai_router_v1_2_1 import AIResult
from content_agent.evidence_pack import EvidencePack
from content_agent.fact_guard_v1_4_rc17 import guard_rewrite_rc17
from content_agent import rewrite_pipeline_v1_3 as base_pipeline
from content_agent.rewrite_pipeline_v1_4_rc17 import candidate_after_router_rc17


def test_rc17_youtube_cyrillic_source_matches_canonical_brand() -> None:
    result = guard_rewrite_rc17(
        "Tesla показала Cybercab. В салоне электрокара можно смотреть Ютуб, а в багажнике хватает места для вещей.",
        "Tesla показала салон Cybercab",
        "У пасажирів Cybercab є екран, на якому можна дивитися YouTube.",
        language="uk",
    )
    assert result.allowed is True
    assert "youtube" not in result.unsupported_entities


def test_rc17_common_platform_aliases_do_not_create_fake_entities() -> None:
    result = guard_rewrite_rc17(
        "Видео опубликовали в Телеграме и на Ютубе.",
        "Відео з'явилося в Telegram",
        "Відео опублікували в Telegram та YouTube.",
        language="uk",
    )
    assert result.allowed is True


def test_rc17_unknown_model_is_still_strict() -> None:
    result = guard_rewrite_rc17(
        "Tesla показала Cybercab без руля и педалей.",
        "Tesla показала Cybercab",
        "Компанія також показала Cybertruck нового покоління.",
        language="uk",
    )
    assert result.allowed is False
    assert "cybertruck" in result.unsupported_entities


def test_rc17_false_alias_positive_returns_first_candidate_without_repair(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_router_call(prompt: str, local_prompt: str, **kwargs: object) -> AIResult:
        del local_prompt
        calls.append({"prompt": prompt, **kwargs})
        return AIResult(
            '{"headline":"Tesla показала Cybercab","fact_card":"",'
            '"rewrite":"У салоні Cybercab є екран, на якому можна дивитися YouTube."}',
            "codex",
            "codex-chatgpt",
            "Codex / ChatGPT",
            1,
            ("Codex / ChatGPT",),
        )

    monkeypatch.setattr(base_pipeline, "_router_call", fake_router_call)
    evidence = EvidencePack(
        text="Tesla показала Cybercab. В салоне можно смотреть Ютуб.",
        source_count=1,
        selected_sentences=2,
        total_sentences=2,
        truncated=False,
    )

    candidate = candidate_after_router_rc17(
        "PROMPT",
        "LOCAL",
        evidence,
        language="uk",
        max_candidates=4,
    )

    assert candidate.guard.allowed is True
    assert len(calls) == 1


def test_rc17_uses_only_one_fact_repair_across_fresh_provider_attempts(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    responses = [
        AIResult(
            '{"headline":"Фінансування","fact_card":"","rewrite":"Програма отримала 600 тис. доларів."}',
            "codex", "codex-chatgpt", "Codex / ChatGPT", 1, ("Codex / ChatGPT",),
        ),
        AIResult(
            '{"headline":"Фінансування","fact_card":"","rewrite":"Програма отримала 700 тис. доларів."}',
            "codex", "codex-chatgpt", "Codex / ChatGPT", 1, ("Codex / ChatGPT",),
        ),
        AIResult(
            '{"headline":"Фінансування","fact_card":"","rewrite":"Програма отримала 800 тис. доларів."}',
            "groq", "openai/gpt-oss-120b", "GPT-OSS 120B / Groq", 1, ("GPT-OSS",),
        ),
        AIResult(
            '{"headline":"Фінансування","fact_card":"","rewrite":"Програма отримала 500 тис. доларів."}',
            "nvidia", "nvidia/nemotron", "Nemotron / NVIDIA", 1, ("Nemotron",),
        ),
    ]

    def fake_router_call(prompt: str, local_prompt: str, **kwargs: object) -> AIResult:
        del local_prompt
        calls.append({"prompt": prompt, **kwargs})
        return responses.pop(0)

    monkeypatch.setattr(base_pipeline, "_router_call", fake_router_call)
    evidence = EvidencePack(
        text="Програма отримала 500 тис. доларів.",
        source_count=1,
        selected_sentences=1,
        total_sentences=1,
        truncated=False,
    )

    candidate = candidate_after_router_rc17(
        "PROMPT",
        "LOCAL",
        evidence,
        language="uk",
        max_candidates=4,
    )

    assert candidate.guard.allowed is True
    assert "500 тис." in candidate.rewrite
    repair_prompts = [str(call["prompt"]) for call in calls if "FACT-SAFE REPAIR" in str(call["prompt"])]
    assert len(repair_prompts) == 1
