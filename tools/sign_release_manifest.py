from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def canonical(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and sign UA FREE Content Tool release manifest")
    parser.add_argument("--version", required=True)
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--private-key", required=True, type=Path, help="offline raw Ed25519 key encoded as base64")
    parser.add_argument("--minimum-updater-version", default="2.0.0-rc50")
    parser.add_argument("--rollback-version", default="")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    archive = args.zip.resolve()
    raw_key = base64.b64decode(args.private_key.read_text(encoding="ascii").strip(), validate=True)
    if len(raw_key) != 32:
        raise SystemExit("private key must decode to exactly 32 bytes")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    payload: dict[str, object] = {
        "schema": "ua-free-content-tool-release-v1",
        "version": args.version,
        "asset_name": archive.name,
        "sha256": digest,
        "minimum_updater_version": args.minimum_updater_version,
        "rollback_version": args.rollback_version,
    }
    signature = Ed25519PrivateKey.from_private_bytes(raw_key).sign(canonical(payload))
    target = args.out or archive.with_name(f"release-manifest-{args.version}.json")
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    target.with_suffix(target.suffix + ".sig").write_text(base64.b64encode(signature).decode("ascii") + "\n", encoding="ascii")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
