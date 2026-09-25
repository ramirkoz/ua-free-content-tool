from content_agent.fact_guard import extract_latin_entities, extract_numbers, guard_rewrite


def test_roman_century_matches_arabic_source_number() -> None:
    source = "Топ-100 лучших сериалов 21 века собрали The New York Times."
    output = "The New York Times назвав топ-100 серіалів XXI століття."
    result = guard_rewrite(source, "Топ серіалів XXI століття", output)
    assert result.allowed
    assert "21" in extract_numbers(source)
    assert "21" in extract_numbers(output)
    assert "xxi" not in extract_latin_entities(output)


def test_mismatched_roman_value_is_blocked() -> None:
    result = guard_rewrite(
        "Подія сталася у 21 столітті.",
        "Подія XXII століття",
        "Подія сталася у XXII столітті.",
    )
    assert not result.allowed
    assert "22" in result.unsupported_numbers
