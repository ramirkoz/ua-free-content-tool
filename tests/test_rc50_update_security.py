from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from content_agent.v2.update_security import (
    ReleaseManifest,
    ReleaseVerificationError,
    verify_artifact,
    verify_manifest,
)


# Test-only key; the real release private key never enters the repository.
_TEST_PRIVATE_RAW = bytes.fromhex(
    "1f1e1d1c1b1a191817161514131211100f0e0d0c0b0a09080706050403020100"
)


def _signed(manifest: ReleaseManifest) -> tuple[bytes, str, str]:
    private = Ed25519PrivateKey.from_private_bytes(_TEST_PRIVATE_RAW)
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    payload = manifest.canonical_bytes()
    signature = private.sign(payload)
    return payload, base64.b64encode(signature).decode(), base64.b64encode(public).decode()


def test_signed_release_manifest_is_fail_closed(tmp_path) -> None:
    artifact = tmp_path / "package.zip"
    artifact.write_bytes(b"rc50-package")
    manifest = ReleaseManifest(
        version="2.0.0-rc50",
        artifact=artifact.name,
        sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
        download_url="https://example.invalid/package.zip",
        minimum_updater_version="2.0.0-rc50",
        rollback_version="2.0.0-rc49",
    )
    payload, signature, public = _signed(manifest)
    parsed = verify_manifest(payload, signature, public_key_b64=public)
    verify_artifact(artifact, parsed)

    tampered = payload.replace(b"rc50", b"rc51", 1)
    with pytest.raises(ReleaseVerificationError):
        verify_manifest(tampered, signature, public_key_b64=public)

    artifact.write_bytes(b"tampered")
    with pytest.raises(ReleaseVerificationError):
        verify_artifact(artifact, parsed)
