from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ...network import fetch_url
from ...paths import runtime_dir
from .control import RemoteCommand
from .release_manifest import verify_manifest

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
    manifest_url: str = ""
    signature_url: str = ""


def select_release(payload: Any, *, current_version: str) -> ReleaseCandidate | None:
    """Select only releases that expose the signed-manifest asset pair.

    GitHub's asset digest is useful transport metadata but lives in the same trust
    domain as the binary. RC50 therefore refuses automatic application unless an
    Ed25519-authenticated manifest is independently verifiable by the embedded key.
    """
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
        manifest_name = f"release-manifest-{version}.json"
        signature_name = manifest_name + ".sig"
        assets = item.get("assets") if isinstance(item.get("assets"), list) else []
        by_name = {
            str(asset.get("name") or ""): asset
            for asset in assets
            if isinstance(asset, dict)
        }
        binary = by_name.get(expected)
        manifest = by_name.get(manifest_name)
        signature = by_name.get(signature_name)
        if not isinstance(binary, dict) or not isinstance(manifest, dict) or not isinstance(signature, dict):
            continue
        digest = str(binary.get("digest") or "").strip().casefold()
        if digest.startswith("sha256:"):
            digest = digest.split(":", 1)[1]
        if not _SHA_RE.fullmatch(digest):
            continue
        candidates.append(
            ReleaseCandidate(
                version,
                digest,
                expected,
                str(manifest.get("browser_download_url") or ""),
                str(signature.get("browser_download_url") or ""),
            )
        )
    return max(candidates, key=lambda row: _rc(row.version), default=None)


def authenticate_release(candidate: ReleaseCandidate, *, current_version: str) -> ReleaseCandidate:
    prefix = f"https://github.com/{_REPO}/releases/download/v{candidate.version}/"
    if not candidate.manifest_url.startswith(prefix) or not candidate.signature_url.startswith(prefix):
        raise RuntimeError("AUTO_UPDATE_MANIFEST_URL_INVALID")
    manifest_response = fetch_url(
        candidate.manifest_url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "UAFreeContentTool/2-auto-update"},
        max_bytes=256 * 1024,
        allowed_content_types={"application/json", "text/plain", "application/octet-stream"},
        timeout=20,
        max_redirects=3,
        allow_http_errors=True,
    )
    signature_response = fetch_url(
        candidate.signature_url,
        method="GET",
        headers={"Accept": "text/plain", "User-Agent": "UAFreeContentTool/2-auto-update"},
        max_bytes=16 * 1024,
        allowed_content_types={"text/plain", "application/octet-stream"},
        timeout=20,
        max_redirects=3,
        allow_http_errors=True,
    )
    if manifest_response.status != 200 or signature_response.status != 200:
        raise RuntimeError("AUTO_UPDATE_MANIFEST_DOWNLOAD_FAILED")
    payload = manifest_response.json()
    signature = signature_response.body.decode("ascii", errors="strict").strip()
    authenticated = verify_manifest(payload, signature)
    if authenticated.version != candidate.version:
        raise RuntimeError("AUTO_UPDATE_MANIFEST_VERSION_MISMATCH")
    if authenticated.asset_name != candidate.asset_name:
        raise RuntimeError("AUTO_UPDATE_MANIFEST_ASSET_MISMATCH")
    if authenticated.sha256 != candidate.sha256:
        raise RuntimeError("AUTO_UPDATE_MANIFEST_DIGEST_MISMATCH")
    minimum = str(authenticated.minimum_updater_version or "").strip()
    if minimum and _rc(current_version) < _rc(minimum):
        raise RuntimeError(f"AUTO_UPDATE_UPDATER_TOO_OLD: requires {minimum}")
    return candidate


class AutonomousUpdateManager:
    CHECK_INTERVAL_SECONDS = 15 * 60

    def __init__(self, *, current_version: str) -> None:
        self.current_version = str(current_version)
        self._last_check_at = 0.0
        self._last_checked_version = self.current_version
        self._last_error = ""
        self._last_triggered = ""
        self._manual_test = ((runtime_dir() / "MANUAL_TEST_BUILD.txt").is_file() or (runtime_dir() / "_runtime" / "MANUAL_TEST_BUILD.txt").is_file())
        self._state = "disabled_manual_test" if self._manual_test else "starting"

    def status(self) -> dict[str, Any]:
        return {
            "enabled": not self._manual_test,
            "mode": "manual-test-disabled" if self._manual_test else "signed-github-release-auto",
            "current_version": self.current_version,
            "latest_checked_version": self._last_checked_version,
            "state": self._state,
            "last_error": self._last_error,
            "check_interval_seconds": self.CHECK_INTERVAL_SECONDS,
            "signature_required": True,
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
                self._state = "up_to_date_or_unsigned"
                self._last_error = ""
                return None
            candidate = authenticate_release(candidate, current_version=self.current_version)
            self._last_checked_version = candidate.version
            self._state = "authenticated_update_available"
            self._last_error = ""
            return candidate
        except Exception as exc:
            self._state = "check_failed_closed"
            self._last_error = str(exc)[:500]
            return None

    def command_for(self, candidate: ReleaseCandidate) -> RemoteCommand | None:
        if self._manual_test:
            return None
        if candidate.version == self._last_triggered:
            return None
        self._last_triggered = candidate.version
        self._state = "preparing_authenticated_update"
        request_id = "auto-" + candidate.version.replace(".", "-")
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return RemoteCommand(request_id=request_id, command="update", created_at=created, target_version=candidate.version)
