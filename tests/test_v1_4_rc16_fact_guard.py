from content_agent.ai_router_v1_2_1 import AIResult
from content_agent.evidence_pack import EvidencePack
from content_agent.fact_guard import extract_numbers, guard_rewrite
from content_agent import rewrite_pipeline_v1_3 as base_pipeline
from content_agent.rewrite_pipeline_v1_4_rc16 import candidate_after_router_rc16


def test_rc16_ru_ua_thousand_translation_is_same_fact() -> None:
    source = (
        "Канада привлекла 64 профессора, получивших 541 млн долл. на научные исследования. "
        "Каждый получает от 500 тыс. до 1 млн долл. в год."
    )
    result = guard_rewrite(
        source,
        "Канада залучила 64 професорів",
        (
            "Канада залучила 64 професорів, які отримали 541 млн доларів на наукові дослідження. "
            "Кожен отримуватиме від 500 тис. до 1 млн доларів на рік."
        ),
        language="uk",
    )
    assert result.allowed is True
    assert result.unsupported_numbers == ()


def test_rc16_common_scale_spellings_normalize_to_same_value() -> None:
    expected = {"500000"}
    assert extract_numbers("500 тыс.") == expected
    assert extract_numbers("500 тис.") == expected
    assert extract_numbers("500 thousand") == expected
    assert extract_numbers("500k") == expected
    assert extract_numbers("500,000") == expected
    assert extract_numbers("0.5 million") == expected


def test_rc16_billions_normalize_across_english_and_ukrainian() -> None:
    assert extract_numbers("1.7 billion") == {"1700000000"}
    assert extract_numbers("1,7 млрд") == {"1700000000"}


def test_rc16_currency_prefix_and_translated_currency_match() -> None:
    result = guard_rewrite(
        "$0.5 million was allocated to the programme.",
        "На програму виділили кошти",
        "На програму виділили 500 тис. доларів.",
        language="uk",
    )
    assert result.allowed is True


def test_rc16_units_stay_distinct_after_normalization() -> None:
    good = guard_rewrite(
        "The distance is 12 km.",
        "Відстань",
        "Відстань становить 12 км.",
        language="uk",
    )
    bad = guard_rewrite(
        "The distance is 12 km.",
        "Вага",
        "Вага становить 12 кг.",
        language="uk",
    )
    assert good.allowed is True
    assert bad.allowed is False
    assert "12 kg" in bad.unsupported_numbers


def test_rc16_still_rejects_genuinely_new_number() -> None:
    result = guard_rewrite(
        "Каждый получает от 500 тыс. до 1 млн долл. в год.",
        "Фінансування",
        "Кожен отримуватиме від 600 тис. до 1 млн доларів на рік.",
        language="uk",
    )
    assert result.allowed is False
    assert "600000" in result.unsupported_numbers


def test_rc16_fact_guard_reject_gets_one_same_provider_correction(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_router_call(prompt: str, local_prompt: str, **kwargs: object) -> AIResult:
        del local_prompt
        calls.append({"prompt": prompt, **kwargs})
        if len(calls) == 1:
            text = (
                '{"headline":"Канада фінансує дослідження","fact_card":"",'
                '"rewrite":"Канада фінансує наукові дослідження. Кожен професор отримуватиме 600 тис. доларів на рік."}'
            )
        else:
            text = (
                '{"headline":"Канада фінансує дослідження","fact_card":"",'
                '"rewrite":"Канада фінансує наукові дослідження. Кожен професор отримуватиме 500 тис. доларів на рік."}'
            )
        return AIResult(text, "codex", "codex-chatgpt", "Codex / ChatGPT", 1, ("Codex / ChatGPT",))

    monkeypatch.setattr(base_pipeline, "_router_call", fake_router_call)
    evidence = EvidencePack(
        text="Канада фінансує наукові дослідження. Кожен професор отримує 500 тис. доларів на рік.",
        source_count=1,
        selected_sentences=2,
        total_sentences=2,
        truncated=False,
    )

    candidate = candidate_after_router_rc16(
        "PROMPT",
        "LOCAL",
        evidence,
        language="uk",
        max_candidates=2,
    )

    assert candidate.guard.allowed is True
    assert "500 тис." in candidate.rewrite
    assert len(calls) == 2
    assert "FACT GUARD REPAIR ONLY" in str(calls[1]["prompt"])
    assert calls[1]["skip_providers"] == {"gemini", "nvidia", "groq", "cloudflare", "local"}
