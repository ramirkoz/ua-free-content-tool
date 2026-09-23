from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ...paths import runtime_dir

from ...network import fetch_url
from .control import RemoteCommand

_REPO = "ramirkoz/ua-free-content-tool"
_VERSION_RE = re.compile(r"^2\.0\.0-rc(?P<rc>[1-9]\d*)$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _rc(value: str) -> int:
    m = _VERSION_RE.fullmatch(str(value or "").strip())
    return int(m.group("rc")) if m else -1


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
    version: str
    sha256: str
    asset_name: str


def select_release(payload: Any, *, current_version: str) -> ReleaseCandidate | None:
    if not isinstance(payload, list):
        return None
    current = _rc(current_version)
    candidates: list[ReleaseCandidate] = []
    for item in payload:
        if not isinstance(item, dict) or bool(item.get("draft")):
            continue
        tag = str(item.get("tag_name") or "").strip()
        version = tag[1:] if tag.startswith("v") else tag
        if _rc(version) <= current:
            continue
        expected = f"UA_FREE_Content_Tool_v{version}_Windows_Portable.zip"
        assets = item.get("assets") if isinstance(item.get("assets"), list) else []
        for asset in assets:
            if not isinstance(asset, dict) or str(asset.get("name") or "") != expected:
                continue
            digest = str(asset.get("digest") or "").strip().casefold()
            if digest.startswith("sha256:"):
                digest = digest.split(":", 1)[1]
            if not _SHA_RE.fullmatch(digest):
                continue
            candidates.append(ReleaseCandidate(version, digest, expected))
    return max(candidates, key=lambda row: _rc(row.version), default=None)


class AutonomousUpdateManager:
    CHECK_INTERVAL_SECONDS = 15 * 60

    def __init__(self, *, current_version: str) -> None:
        self.current_version = str(current_version)
        self._last_check_at = 0.0
        self._last_checked_version = self.current_version
        self._last_error = ""
        self._last_triggered = ""
        self._manual_test = (runtime_dir() / "MANUAL_TEST_BUILD.txt").is_file()
        self._state = "disabled_manual_test" if self._manual_test else "starting"

    def status(self) -> dict[str, Any]:
        return {
            "enabled": not self._manual_test,
            "mode": "manual-test-disabled" if self._manual_test else "github-release-auto",
            "current_version": self.current_version,
            "latest_checked_version": self._last_checked_version,
            "state": self._state,
            "last_error": self._last_error,
            "check_interval_seconds": self.CHECK_INTERVAL_SECONDS,
        }

    def due(self) -> bool:
        if self._manual_test:
            return False
        return self._last_check_at <= 0 or time.monotonic() - self._last_check_at >= self.CHECK_INTERVAL_SECONDS

    def check(self) -> ReleaseCandidate | None:
        if self._manual_test:
            self._state = "disabled_manual_test"
            return None
        self._last_check_at = time.monotonic()
        try:
            response = fetch_url(
                f"https://api.github.com/repos/{_REPO}/releases?per_page=20",
                method="GET",
                headers={"Accept": "application/vnd.github+json", "User-Agent": "UAFreeContentTool/2-auto-update"},
                max_bytes=4 * 1024 * 1024,
                allowed_content_types={"application/json"},
                timeout=25,
                max_redirects=0,
                allow_http_errors=True,
            )
            if response.status != 200:
                raise RuntimeError(f"AUTO_UPDATE_RELEASE_LOOKUP_HTTP_{response.status}")
            candidate = select_release(response.json(), current_version=self.current_version)
            if candidate is None:
                self._last_checked_version = self.current_version
                self._state = "up_to_date"
                self._last_error = ""
                return None
            self._last_checked_version = candidate.version
            self._state = "update_available"
            self._last_error = ""
            return candidate
        except Exception as exc:
            self._state = "check_failed"
            self._last_error = str(exc)[:500]
            return None

    def command_for(self, candidate: ReleaseCandidate) -> RemoteCommand | None:
        if self._manual_test:
            return None
        if candidate.version == self._last_triggered:
            return None
        self._last_triggered = candidate.version
        self._state = "preparing_update"
        request_id = "auto-" + candidate.version.replace(".", "-")
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return RemoteCommand(request_id=request_id, command="update", created_at=created, target_version=candidate.version)
