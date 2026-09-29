from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# RC50 release-signing public key. The matching private key is intentionally not
# stored in the repository or portable runtime and must remain offline/release-only.
_RELEASE_PUBLIC_KEY_B64 = "TbpUi5OSK0oX8V8u6CgRsU64vRbBLbcKMVWGar5nKbI="
_SCHEMA = "ua-free-content-tool-release-v1"


@dataclass(frozen=True, slots=True)
class AuthenticatedRelease:
    version: str
    asset_name: str
    sha256: str
    minimum_updater_version: str
    rollback_version: str


def canonical_manifest_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def public_key() -> Ed25519PublicKey:
    raw = base64.b64decode(_RELEASE_PUBLIC_KEY_B64, validate=True)
    if len(raw) != 32:
        raise RuntimeError("UPDATE_PUBLIC_KEY_INVALID")
    return Ed25519PublicKey.from_public_bytes(raw)


def verify_manifest(payload: Any, signature_b64: str) -> AuthenticatedRelease:
    if not isinstance(payload, dict) or str(payload.get("schema") or "") != _SCHEMA:
        raise RuntimeError("UPDATE_MANIFEST_SCHEMA_INVALID")
    signature = base64.b64decode(str(signature_b64 or "").strip(), validate=True)
    try:
        public_key().verify(signature, canonical_manifest_bytes(payload))
    except (InvalidSignature, ValueError) as exc:
        raise RuntimeError("UPDATE_MANIFEST_SIGNATURE_INVALID") from exc

    version = str(payload.get("version") or "").strip()
    asset_name = str(payload.get("asset_name") or "").strip()
    sha256 = str(payload.get("sha256") or "").strip().casefold()
    minimum = str(payload.get("minimum_updater_version") or "").strip()
    rollback = str(payload.get("rollback_version") or "").strip()
    if not version or not asset_name or len(sha256) != 64 or any(ch not in "0123456789abcdef" for ch in sha256):
        raise RuntimeError("UPDATE_MANIFEST_FIELDS_INVALID")
    return AuthenticatedRelease(version, asset_name, sha256, minimum, rollback)


__all__ = ["AuthenticatedRelease", "canonical_manifest_bytes", "public_key", "verify_manifest"]
