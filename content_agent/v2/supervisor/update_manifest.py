from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MANIFEST_SCHEMA = "ua-free-content-tool-update-manifest-v1"
UPDATER_VERSION = 1
# Public verification key only. The signing private key must never ship with the app.
EMBEDDED_PUBLIC_KEY_B64 = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^2\.0\.0-rc[1-9]\d*$")


@dataclass(frozen=True, slots=True)
class VerifiedUpdateManifest:
    version: str
    asset_name: str
    sha256: str
    min_updater_version: int
    rollback_supported: bool


def canonical_manifest_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def verify_manifest(
    payload: dict[str, Any],
    signature_b64: str,
    *,
    public_key_b64: str = EMBEDDED_PUBLIC_KEY_B64,
    updater_version: int = UPDATER_VERSION,
) -> VerifiedUpdateManifest:
    if not isinstance(payload, dict) or payload.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("UPDATE_MANIFEST_SCHEMA_INVALID")
    version = str(payload.get("version") or "").strip()
    asset_name = str(payload.get("asset_name") or "").strip()
    sha256 = str(payload.get("sha256") or "").strip().casefold()
    try:
        minimum = int(payload.get("min_updater_version"))
    except (TypeError, ValueError) as exc:
        raise ValueError("UPDATE_MANIFEST_MIN_UPDATER_INVALID") from exc
    rollback = payload.get("rollback")
    rollback_supported = bool(isinstance(rollback, dict) and rollback.get("supported") is True)
    if not _VERSION_RE.fullmatch(version):
        raise ValueError("UPDATE_MANIFEST_VERSION_INVALID")
    expected_asset = f"UA_FREE_Content_Tool_v{version}_Windows_Portable.zip"
    if asset_name != expected_asset:
        raise ValueError("UPDATE_MANIFEST_ASSET_INVALID")
    if not _SHA256_RE.fullmatch(sha256):
        raise ValueError("UPDATE_MANIFEST_SHA256_INVALID")
    if minimum < 1 or minimum > int(updater_version):
        raise ValueError("UPDATE_MANIFEST_UPDATER_TOO_OLD")
    if not rollback_supported:
        raise ValueError("UPDATE_MANIFEST_ROLLBACK_REQUIRED")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
        signature = base64.b64decode(str(signature_b64 or "").strip(), validate=True)
        public_key.verify(signature, canonical_manifest_bytes(payload))
    except (ValueError, InvalidSignature) as exc:
        raise ValueError("UPDATE_MANIFEST_SIGNATURE_INVALID") from exc
    return VerifiedUpdateManifest(version, asset_name, sha256, minimum, True)


__all__ = [
    "MANIFEST_SCHEMA",
    "UPDATER_VERSION",
    "EMBEDDED_PUBLIC_KEY_B64",
    "VerifiedUpdateManifest",
    "canonical_manifest_bytes",
    "verify_manifest",
]
