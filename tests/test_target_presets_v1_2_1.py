from __future__ import annotations

import json

from content_agent.target_presets_v1_2_1 import (
    LAST_SELECTION_LABEL,
    TargetPresetState,
    load_target_preset_state,
    matching_preset_name,
    normalize_target_keys,
    save_target_preset_state,
)


def test_normalize_target_keys_keeps_order_and_removes_duplicates() -> None:
    assert normalize_target_keys([
        "threads",
        " telegram ",
        "threads",
        "",
        None,
        "linkedin",
    ]) == ["threads", "telegram", "linkedin"]


def test_target_presets_round_trip_in_data_file(tmp_path) -> None:
    path = tmp_path / "publication_target_sets.json"
    state = TargetPresetState(
        last_targets=["facebook:123", "threads", "linkedin", "telegram"],
        presets={
            "Основний": ["facebook:123", "threads", "linkedin", "telegram"],
            "Короткий": ["facebook:123", "telegram"],
        },
    )

    save_target_preset_state(path, state)
    loaded = load_target_preset_state(path)

    assert loaded.last_targets == ["facebook:123", "threads", "linkedin", "telegram"]
    assert loaded.presets["Основний"] == ["facebook:123", "threads", "linkedin", "telegram"]
    assert loaded.presets["Короткий"] == ["facebook:123", "telegram"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1


def test_reserved_last_selection_label_is_not_saved_as_named_preset(tmp_path) -> None:
    path = tmp_path / "publication_target_sets.json"
    save_target_preset_state(
        path,
        TargetPresetState(
            last_targets=["telegram"],
            presets={
                LAST_SELECTION_LABEL: ["linkedin"],
                "Нормальний": ["telegram"],
            },
        ),
    )

    loaded = load_target_preset_state(path)
    assert LAST_SELECTION_LABEL not in loaded.presets
    assert loaded.presets == {"Нормальний": ["telegram"]}


def test_matching_preset_ignores_target_order() -> None:
    state = TargetPresetState(
        presets={
            "Основний": ["facebook:123", "threads", "linkedin", "telegram"],
            "Два": ["facebook:123", "telegram"],
        }
    )

    assert matching_preset_name(
        state,
        ["telegram", "linkedin", "facebook:123", "threads"],
    ) == "Основний"
    assert matching_preset_name(state, ["telegram", "threads"]) is None


def test_corrupt_target_preset_file_fails_empty(tmp_path) -> None:
    path = tmp_path / "publication_target_sets.json"
    path.write_text("{ definitely not json", encoding="utf-8")

    loaded = load_target_preset_state(path)

    assert loaded.last_targets == []
    assert loaded.presets == {}
