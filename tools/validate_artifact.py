from __future__ import annotations

import hashlib
import os
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_manifest(text: str) -> dict[str, str]:
    records: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, name = line.split("  ", 1)
        if len(digest) != 64 or name in records:
            raise ValueError("Invalid manifest record")
        records[name] = digest
    return records


def validate_tree(root: Path) -> None:
    manifest_path = root / "FILE_MANIFEST.sha256"
    manifest = parse_manifest(manifest_path.read_text(encoding="utf-8"))
    actual: dict[str, str] = {}
    forbidden = {"__pycache__", ".pytest_cache", ".venv", ".venv-build", "Release"}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if any(part in forbidden for part in path.relative_to(root).parts):
            raise ValueError(f"Forbidden generated artifact: {relative}")
        if path.is_symlink():
            raise ValueError(f"Symlink forbidden: {relative}")
        if path.is_file() and relative != "FILE_MANIFEST.sha256":
            actual[relative] = sha256(path)
    if manifest != actual:
        missing = sorted(set(manifest) - set(actual))
        extra = sorted(set(actual) - set(manifest))
        wrong = sorted(name for name in set(actual) & set(manifest) if actual[name] != manifest[name])
        raise ValueError(f"Manifest mismatch missing={missing} extra={extra} wrong={wrong}")


def validate_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"CRC failed: {bad}")
        names = [info.filename for info in archive.infolist()]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP entry names are forbidden")
        roots = {PurePosixPath(name).parts[0] for name in names if name}
        if len(roots) != 1:
            raise ValueError(f"Expected one canonical root, got {roots}")
        root = next(iter(roots))
        allowed_roots = ("UA_FREE_Content_Tool_STABILIZATION_", "UA_FREE_Content_Tool_v")
        if not root.startswith(allowed_roots):
            raise ValueError(f"Unexpected root: {root}")
        forbidden = {"__pycache__", ".pytest_cache", ".venv", ".venv-build", "Release"}
        for info in archive.infolist():
            name = info.filename
            if "\\" in name:
                raise ValueError(f"Backslash in ZIP name: {name}")
            pure = PurePosixPath(name)
            if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
                raise ValueError(f"Unsafe ZIP path: {name}")
            relative_parts = pure.parts[1:]
            if any(part in forbidden for part in relative_parts):
                raise ValueError(f"Forbidden generated artifact in ZIP: {name}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise ValueError(f"Symlink in ZIP: {name}")
        manifest_name = f"{root}/FILE_MANIFEST.sha256"
        manifest = parse_manifest(archive.read(manifest_name).decode("utf-8"))
        actual: dict[str, str] = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            relative = PurePosixPath(info.filename).relative_to(root).as_posix()
            if relative == "FILE_MANIFEST.sha256":
                continue
            actual[relative] = hashlib.sha256(archive.read(info)).hexdigest()
        if manifest != actual:
            raise ValueError("ZIP bytes do not match FILE_MANIFEST.sha256")
    print(f"PASS size={path.stat().st_size} sha256={sha256(path)} root={root} files={len(actual)}")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_artifact.py <source-folder-or-zip>")
        return 2
    target = Path(sys.argv[1]).resolve()
    if target.is_dir():
        validate_tree(target)
        print("PASS source tree")
    else:
        validate_zip(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
