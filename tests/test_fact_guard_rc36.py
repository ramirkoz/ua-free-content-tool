from content_agent.fact_guard import extract_latin_entities, extract_numbers, guard_rewrite


def test_plain_english_words_are_not_model_entities() -> None:
    text = "Destroy the signal. Keep you safe. The story continues."
    entities = extract_latin_entities(text)
    assert "destroy" not in entities
    assert "the" not in entities
    assert "keep" not in entities
    assert "you" not in entities


def test_structured_identifiers_still_count_as_entities() -> None:
    entities = extract_latin_entities("OpenAI tested GPT-5.4 with RTX-5090 hardware.")
    assert "openai" in entities
    assert "gpt-5.4" in entities
    assert "rtx-5090" in entities


def test_unicode_hundred_normalizes_to_100() -> None:
    assert "100" in extract_numbers("топ-💯 серіалів")
    assert "100" in extract_numbers("топ-1️⃣0️⃣0️⃣ серіалів")


def test_plain_english_rewrite_no_longer_fails_entity_guard() -> None:
    source = "Список найкращих серіалів опублікував New York Times. Топ-💯."
    rewrite = "The list keeps the focus on television history. Топ-100."
    result = guard_rewrite(source, "Топ-100 серіалів", rewrite)
    assert result.allowed


def test_genuinely_new_structured_entity_is_blocked() -> None:
    result = guard_rewrite(
        "Компанія показала нову систему.",
        "Нова система",
        "Система працює на OpenAI.",
    )
    assert not result.allowed
    assert "openai" in result.unsupported_entities
