from __future__ import annotations

import argparse
import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SCHEMA = "ua-free-content-tool-release-manifest-v1"


def canonical(value: dict[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sign UA FREE Content Tool release manifest with an offline Ed25519 key.")
    parser.add_argument("--asset", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--minimum-updater-version", default="2.0.0-rc50")
    parser.add_argument("--rollback-version", default="")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd())
    args = parser.parse_args()

    raw_key = args.private_key.read_bytes()
    key = serialization.load_pem_private_key(raw_key, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("private key is not Ed25519")
    digest = hashlib.sha256(args.asset.read_bytes()).hexdigest()
    manifest = {
        "schema": SCHEMA,
        "version": args.version,
        "asset_name": f"UA_FREE_Content_Tool_v{args.version}_Windows_Portable.zip",
        "sha256": digest,
        "minimum_updater_version": args.minimum_updater_version,
        "rollback_version": args.rollback_version,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if args.asset.name != manifest["asset_name"]:
        raise SystemExit(f"asset must be named {manifest['asset_name']}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"UA_FREE_Content_Tool_v{args.version}_release-manifest"
    manifest_path = args.output_dir / f"{stem}.json"
    signature_path = args.output_dir / f"{stem}.sig"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    signature = key.sign(canonical(manifest))
    signature_path.write_text(base64.b64encode(signature).decode("ascii") + "\n", encoding="ascii")
    print(manifest_path)
    print(signature_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
