from __future__ import annotations

from types import SimpleNamespace

import content_agent.ui.v1_4_rc7_window as rc7
from content_agent.target_presets_v1_2_1 import TargetPresetState


class _Var:
    def __init__(self, value: bool = False) -> None:
        self.value = value

    def get(self) -> bool:
        return self.value

    def set(self, value: bool) -> None:
        self.value = bool(value)


def test_rc7_near_fullscreen_geometry_reserves_bottom_work_area() -> None:
    width, height, x, y = rc7.safe_dialog_geometry(1920, 1080)
    assert (x, y) == (0, 0)
    assert width == 1908
    assert height == 984
    assert height < 1080


def test_rc7_real_duplicate_workflow_uses_safe_dialog_class() -> None:
    assert rc7.ai_workflow_v1_3_rc6.GlobalDuplicatesDialog is rc7.Rc7GlobalDuplicatesDialog


def test_rc7_fresh_material_restores_last_used_targets(monkeypatch) -> None:
    monkeypatch.setattr(rc7, "normalize_legacy_target_keys", lambda _config, keys: list(keys))
    monkeypatch.setattr(rc7, "destination_ready", lambda _config, _key: True)

    window = object.__new__(rc7.MainWindow)
    window.config = SimpleNamespace()
    window.target_vars = {
        "facebook:news": _Var(False),
        "telegram": _Var(False),
        "linkedin": _Var(False),
    }
    window._target_preset_state = TargetPresetState(
        last_targets=["facebook:news", "telegram"],
        presets={},
    )
    applied: list[list[str]] = []
    refreshed: list[str | None] = []

    def apply(keys: list[str]) -> None:
        applied.append(list(keys))
        wanted = set(keys)
        for key, variable in window.target_vars.items():
            variable.set(key in wanted)

    window._apply_target_keys = apply
    window._refresh_target_preset_controls = lambda preferred=None: refreshed.append(preferred)

    rc7.MainWindow.apply_recommendations(window, ["linkedin"])

    assert applied == [["facebook:news", "telegram"]]
    assert window.target_vars["facebook:news"].get() is True
    assert window.target_vars["telegram"].get() is True
    assert window.target_vars["linkedin"].get() is False
    assert refreshed


def test_rc7_version_label() -> None:
    assert rc7.MainWindow.VERSION_LABEL == "1.4.0-rc7"
