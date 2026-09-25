from content_agent.fact_guard import extract_numbers, guard_rewrite


def test_full_form_kilometres_match_abbreviation() -> None:
    source = (
        "Дрон може літати на висоті до 8 кілометрів. "
        "Двигун розганяє дрон до 450–500 кілометрів на годину."
    )
    output = "Дрон працює на висоті 8 км і розганяється до 500 км."
    result = guard_rewrite(source, "Характеристики дрона", output)
    assert result.allowed
    assert "8 km" in extract_numbers(source)
    assert "500 km" in extract_numbers(source)


def test_russian_full_form_kilometres_match_abbreviation() -> None:
    source = "Высота 8 километров, скорость до 500 километров в час."
    output = "Висота 8 км, швидкість до 500 км."
    assert guard_rewrite(source, "Дані", output).allowed


def test_measurement_word_forms_normalize() -> None:
    assert extract_numbers("5 метрів") == {"5 m"}
    assert extract_numbers("5 метров") == {"5 m"}
    assert extract_numbers("5 meters") == {"5 m"}
    assert extract_numbers("12 кілограмів") == {"12 kg"}
    assert extract_numbers("12 килограммов") == {"12 kg"}
    assert extract_numbers("12 kilograms") == {"12 kg"}
    assert extract_numbers("10 мегаватів") == {"10 mw"}
    assert extract_numbers("10 megawatts") == {"10 mw"}


def test_real_unit_change_remains_blocked() -> None:
    result = guard_rewrite(
        "Висота 8 кілометрів.",
        "Висота",
        "Висота 9 км.",
    )
    assert not result.allowed
    assert "9 km" in result.unsupported_numbers
