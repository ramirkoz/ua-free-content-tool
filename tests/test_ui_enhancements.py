from __future__ import annotations

from pathlib import Path

from content_agent.ui.main_window_enhancements import (
    history_prediction_label,
    read_public_version,
    tree_sort_key,
)


def test_public_version_matches_repository_metadata() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = (root / "PUBLIC_VERSION.txt").read_text(encoding="utf-8").strip()
    assert read_public_version(root) == expected


def test_history_prediction_label_distinguishes_saved_states() -> None:
    assert history_prediction_label({}) == "—"
    assert history_prediction_label({"history_prediction": {"available": False}}) == "Недостатньо даних"
    assert (
        history_prediction_label(
            {"history_prediction": {"available": True, "score": 68, "confidence": 54}}
        )
        == "68/100 · 54%"
    )
    assert (
        history_prediction_label(
            {"history_prediction": {"available": False}},
            "en",
        )
        == "Insufficient data"
    )


def test_tree_sort_key_handles_numbers_dates_text_and_empty_values() -> None:
    assert tree_sort_key("39/100") < tree_sort_key("68/100")
    assert tree_sort_key("2026-08-05T06:00:00+00:00") < tree_sort_key("2026-08-06T06:00:00+00:00")
    assert tree_sort_key("Альфа") < tree_sort_key("Бета")
    assert tree_sort_key("—")[0] == 3
