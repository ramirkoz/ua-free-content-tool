from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# RC50 release verification key. The matching private key is intentionally not in
# the repository or portable build and is used only for offline release signing.
RELEASE_PUBLIC_KEY_B64 = "y0K92B7rh/BBShro2UgcgJjDBZmSOVuBq4zWgVNrTDQ="
MANIFEST_SCHEMA = 1


class ReleaseVerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    version: str
    artifact: str
    sha256: str
    download_url: str
    minimum_updater_version: str
    rollback_version: str
    schema: int = MANIFEST_SCHEMA

    def payload(self) -> dict[str, object]:
        return {
            "artifact": self.artifact,
            "download_url": self.download_url,
            "minimum_updater_version": self.minimum_updater_version,
            "rollback_version": self.rollback_version,
            "schema": int(self.schema),
            "sha256": self.sha256.lower(),
            "version": self.version,
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> "ReleaseManifest":
        required = {
            "version", "artifact", "sha256", "download_url",
            "minimum_updater_version", "rollback_version", "schema",
        }
        if set(value) != required:
            missing = sorted(required - set(value))
            extra = sorted(set(value) - required)
            raise ReleaseVerificationError(
                f"Неправильний release manifest: missing={missing}, extra={extra}."
            )
        schema = int(value["schema"])
        if schema != MANIFEST_SCHEMA:
            raise ReleaseVerificationError(f"Непідтримувана схема release manifest: {schema}.")
        sha = str(value["sha256"] or "").strip().lower()
        if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            raise ReleaseVerificationError("Release manifest містить неправильний SHA-256.")
        url = str(value["download_url"] or "").strip()
        if not url.startswith("https://"):
            raise ReleaseVerificationError("Release manifest дозволяє лише HTTPS download URL.")
        return cls(
            version=str(value["version"] or "").strip(),
            artifact=str(value["artifact"] or "").strip(),
            sha256=sha,
            download_url=url,
            minimum_updater_version=str(value["minimum_updater_version"] or "").strip(),
            rollback_version=str(value["rollback_version"] or "").strip(),
            schema=schema,
        )


def verify_manifest(
    manifest_bytes: bytes,
    signature_b64: str,
    *,
    public_key_b64: str = RELEASE_PUBLIC_KEY_B64,
) -> ReleaseManifest:
    try:
        value = json.loads(manifest_bytes.decode("utf-8"))
    except Exception as exc:
        raise ReleaseVerificationError("Release manifest не є коректним UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise ReleaseVerificationError("Release manifest root має бути JSON object.")
    manifest = ReleaseManifest.from_mapping(value)
    canonical = manifest.canonical_bytes()
    # Reject alternative JSON serializations before signature verification. This
    # keeps one byte-level canonical representation for offline signing.
    if manifest_bytes.strip() != canonical:
        raise ReleaseVerificationError("Release manifest не в канонічному форматі.")
    try:
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
        signature = base64.b64decode(str(signature_b64).strip(), validate=True)
        public.verify(signature, canonical)
    except (ValueError, InvalidSignature) as exc:
        raise ReleaseVerificationError("Підпис release manifest недійсний.") from exc
    return manifest


def verify_artifact(path: Path, manifest: ReleaseManifest) -> None:
    target = Path(path)
    if target.name != manifest.artifact:
        raise ReleaseVerificationError(
            f"Назва артефакту не збігається з manifest: {target.name} != {manifest.artifact}."
        )
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    actual = digest.hexdigest().lower()
    if actual != manifest.sha256:
        raise ReleaseVerificationError(
            f"SHA-256 артефакту не збігається: {actual} != {manifest.sha256}."
        )


__all__ = [
    "MANIFEST_SCHEMA",
    "RELEASE_PUBLIC_KEY_B64",
    "ReleaseManifest",
    "ReleaseVerificationError",
    "verify_artifact",
    "verify_manifest",
]
