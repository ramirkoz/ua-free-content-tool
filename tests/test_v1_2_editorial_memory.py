from __future__ import annotations

from content_agent.ui.v1_2_window import (
    editorial_memory_clear_prompt,
    editorial_memory_texts,
    format_editorial_memory_stats,
)


def test_editorial_memory_labels_explain_that_ollama_is_not_retrained() -> None:
    uk = editorial_memory_texts("uk")
    en = editorial_memory_texts("en")
    assert uk["title"] == "Редакційна пам’ять"
    assert "не перенавчає" in uk["explanation"]
    assert "does not retrain" in en["explanation"]
    assert uk["enabled"].startswith("Використовувати попередні схвалені тексти")


def test_editorial_memory_stats_are_readable_and_multiline() -> None:
    stats = {
        "editorial_examples": {"uk": 16, "en": 2},
        "topic_feedback": 99,
        "events": 140,
        "active_exclusions": 51,
    }
    uk = format_editorial_memory_stats(stats, "uk")
    en = format_editorial_memory_stats(stats, "en")
    assert "Схвалених текстів українською: 16" in uk
    assert "Активних правил виключення: 51" in uk
    assert uk.count("\n") == 4
    assert "Approved English texts: 2" in en


def test_clear_prompt_states_exactly_what_remains() -> None:
    stats = {
        "editorial_examples": {"uk": 16, "en": 0},
        "topic_feedback": 99,
        "events": 140,
        "active_exclusions": 51,
    }
    prompt = editorial_memory_clear_prompt(stats, "uk")
    assert "схвалені тексти: UK 16, EN 0" in prompt
    assert "рішення щодо схожості й об’єднання: 99" in prompt
    assert "активні правила виключення: 51" in prompt
    assert "Не буде видалено" in prompt
