from content_agent.fact_guard import extract_numbers, guard_rewrite


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
