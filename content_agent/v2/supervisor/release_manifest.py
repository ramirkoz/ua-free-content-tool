from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# Project release-signing public key. The corresponding private key is never
# stored in the repository, portable package, Data or GitHub release.
_RELEASE_PUBLIC_KEY_B64 = "I9zit1ypf5IbrxwXDjF0v6yEGtcVjS0vxHabM/rzwqI="
_SCHEMA = "ua-free-content-tool-release-manifest-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^2\.0\.0-rc[1-9]\d*$")


class ReleaseManifestError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedReleaseManifest:
    version: str
    asset_name: str
    sha256: str
    minimum_updater_version: str
    rollback_version: str
    created_at: str


def canonical_manifest_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _validated_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReleaseManifestError("UPDATE_MANIFEST_NOT_OBJECT")
    expected = {
        "schema", "version", "asset_name", "sha256", "minimum_updater_version",
        "rollback_version", "created_at",
    }
    if set(value) != expected or value.get("schema") != _SCHEMA:
        raise ReleaseManifestError("UPDATE_MANIFEST_SCHEMA_INVALID")
    version = str(value.get("version") or "")
    minimum = str(value.get("minimum_updater_version") or "")
    rollback = str(value.get("rollback_version") or "")
    digest = str(value.get("sha256") or "").casefold()
    asset_name = str(value.get("asset_name") or "")
    if not _VERSION_RE.fullmatch(version):
        raise ReleaseManifestError("UPDATE_MANIFEST_VERSION_INVALID")
    if not _VERSION_RE.fullmatch(minimum):
        raise ReleaseManifestError("UPDATE_MANIFEST_MIN_VERSION_INVALID")
    if rollback and not _VERSION_RE.fullmatch(rollback):
        raise ReleaseManifestError("UPDATE_MANIFEST_ROLLBACK_VERSION_INVALID")
    if not _SHA256_RE.fullmatch(digest):
        raise ReleaseManifestError("UPDATE_MANIFEST_SHA256_INVALID")
    if asset_name != f"UA_FREE_Content_Tool_v{version}_Windows_Portable.zip":
        raise ReleaseManifestError("UPDATE_MANIFEST_ASSET_NAME_INVALID")
    return dict(value)


def verify_release_manifest(manifest_bytes: bytes, signature_bytes: bytes) -> VerifiedReleaseManifest:
    if len(manifest_bytes) > 64 * 1024 or len(signature_bytes) > 4096:
        raise ReleaseManifestError("UPDATE_MANIFEST_TOO_LARGE")
    try:
        value = json.loads(manifest_bytes.decode("utf-8"))
    except Exception as exc:
        raise ReleaseManifestError("UPDATE_MANIFEST_JSON_INVALID") from exc
    payload = _validated_payload(value)
    try:
        signature_text = signature_bytes.decode("ascii").strip()
        signature = base64.b64decode(signature_text, validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(_RELEASE_PUBLIC_KEY_B64, validate=True))
        public_key.verify(signature, canonical_manifest_bytes(payload))
    except Exception as exc:
        raise ReleaseManifestError("UPDATE_MANIFEST_SIGNATURE_INVALID") from exc
    return VerifiedReleaseManifest(
        version=str(payload["version"]),
        asset_name=str(payload["asset_name"]),
        sha256=str(payload["sha256"]),
        minimum_updater_version=str(payload["minimum_updater_version"]),
        rollback_version=str(payload["rollback_version"]),
        created_at=str(payload["created_at"]),
    )


def manifest_schema() -> str:
    return _SCHEMA


__all__ = [
    "ReleaseManifestError",
    "VerifiedReleaseManifest",
    "canonical_manifest_bytes",
    "manifest_schema",
    "verify_release_manifest",
]
