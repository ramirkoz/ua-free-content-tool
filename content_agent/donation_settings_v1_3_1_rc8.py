from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path

from .paths import data_dir
from .publication_text import FUND_FOOTER, THREADS_FUND_FOOTER


DEFAULT_PATH_NAME = "donation_settings_v1_3_1_rc8.json"


@dataclass(slots=True)
class DonationSettings:
    text: str = FUND_FOOTER
    targets: list[str] = field(default_factory=list)

    def normalized(self) -> "DonationSettings":
        text = "\n".join(line.rstrip() for line in str(self.text or "").strip().splitlines()).strip()
        if len(text) > 1500:
            text = text[:1500].rstrip()
        targets: list[str] = []
        seen: set[str] = set()
        for raw in self.targets:
            value = str(raw or "").strip()
            if value and value not in seen:
                targets.append(value)
                seen.add(value)
        return DonationSettings(text=text, targets=targets)

    def enabled_for(self, platform: str) -> bool:
        return str(platform or "").strip() in set(self.targets)


def donation_settings_path() -> Path:
    return data_dir() / DEFAULT_PATH_NAME


def load_donation_settings(path: Path | None = None) -> DonationSettings:
    target = path or donation_settings_path()
    if not target.exists():
        return DonationSettings()
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return DonationSettings()
    if not isinstance(payload, dict):
        return DonationSettings()
    raw_targets = payload.get("targets")
    return DonationSettings(
        text=str(payload.get("text") or FUND_FOOTER),
        targets=[str(item) for item in raw_targets] if isinstance(raw_targets, list) else [],
    ).normalized()


def save_donation_settings(settings: DonationSettings, path: Path | None = None) -> DonationSettings:
    target = path or donation_settings_path()
    normalized = settings.normalized()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(
        json.dumps(
            {"text": normalized.text, "targets": normalized.targets},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, target)
    return normalized


def strip_known_donation_blocks(text: str) -> str:
    """Remove only donation blocks shipped by older UA FREE builds.

    Custom user text is never guessed or stripped. This is intentionally narrow
    so queued RC7 payloads can be upgraded without touching the news body.
    """

    value = str(text or "").strip()
    for footer in (FUND_FOOTER, THREADS_FUND_FOOTER):
        value = "\n\n".join(part.strip() for part in value.split(footer) if part.strip()).strip()
    return value


def with_inline_donation(text: str, donation_text: str, enabled: bool) -> str:
    value = strip_known_donation_blocks(text)
    donation = str(donation_text or "").strip()
    if not enabled or not donation:
        return value
    parts = [part.strip() for part in value.split("\n\n") if part.strip()]
    source_index = next((i for i, part in enumerate(parts) if part.startswith("Джерело: ")), None)
    if source_index is None:
        parts.append(donation)
    else:
        parts.insert(source_index, donation)
    return "\n\n".join(parts)
