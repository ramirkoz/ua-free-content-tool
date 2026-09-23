from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


STATE_VERSION = 1
LAST_SELECTION_LABEL = "Останній вибір"


def normalize_target_keys(values: Iterable[object]) -> list[str]:
    """Return stable, unique, non-empty publication target keys."""

    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        key = str(raw or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


@dataclass
class TargetPresetState:
    last_targets: list[str] = field(default_factory=list)
    presets: dict[str, list[str]] = field(default_factory=dict)

    def normalized(self) -> "TargetPresetState":
        cleaned_presets: dict[str, list[str]] = {}
        for raw_name, raw_targets in self.presets.items():
            name = str(raw_name or "").strip()
            if not name or name == LAST_SELECTION_LABEL:
                continue
            targets = normalize_target_keys(raw_targets)
            if targets:
                cleaned_presets[name] = targets
        return TargetPresetState(
            last_targets=normalize_target_keys(self.last_targets),
            presets=cleaned_presets,
        )


def load_target_preset_state(path: Path) -> TargetPresetState:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return TargetPresetState()
    if not isinstance(payload, dict):
        return TargetPresetState()
    presets_raw = payload.get("presets")
    presets: dict[str, list[str]] = {}
    if isinstance(presets_raw, dict):
        for name, targets in presets_raw.items():
            if isinstance(targets, list):
                presets[str(name)] = [str(item) for item in targets]
    last_raw = payload.get("last_targets")
    last_targets = [str(item) for item in last_raw] if isinstance(last_raw, list) else []
    return TargetPresetState(last_targets=last_targets, presets=presets).normalized()


def save_target_preset_state(path: Path, state: TargetPresetState) -> None:
    normalized = state.normalized()
    payload = {
        "version": STATE_VERSION,
        "last_targets": normalized.last_targets,
        "presets": normalized.presets,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def matching_preset_name(state: TargetPresetState, targets: Iterable[object]) -> str | None:
    wanted = set(normalize_target_keys(targets))
    if not wanted:
        return None
    for name, preset_targets in state.normalized().presets.items():
        if set(preset_targets) == wanted:
            return name
    return None
