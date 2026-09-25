from content_agent.fact_guard import extract_numbers, guard_rewrite


def test_apostrophe_grouped_thousands_are_equivalent() -> None:
    source = "1’279 исследований за 30 лет с участием 609’278 человек"
    output = "1279 досліджень за 30 років за участю 609278 людей"
    assert extract_numbers(source) == {"1279", "30", "609278"}
    assert guard_rewrite(source, "Дослідження", output).allowed


def test_short_unit_does_not_consume_word_prefix() -> None:
    assert extract_numbers("25 моделей") == {"25"}
    assert extract_numbers("25 мовних моделей") == {"25"}
    assert extract_numbers("25 м") == {"25 m"}
    assert extract_numbers("25 m") == {"25 m"}


def test_real_unsupported_number_is_still_blocked() -> None:
    result = guard_rewrite("Проверили 25 моделей.", "Тест", "Перевірили 26 моделей.")
    assert not result.allowed
    assert "26" in result.unsupported_numbers
