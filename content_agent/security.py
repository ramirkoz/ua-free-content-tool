from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, urlunsplit

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)([^\s,;]+)"),
    re.compile(r"(?i)(access[_-]?token\s*[:=]\s*)([^\s,;}&]+)"),
    re.compile(r"(?i)(bot\d*:)([A-Za-z0-9_-]{20,})"),
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:EA[A-Za-z0-9]{20,}|AQ[A-Za-z0-9_-]{20,})\b"),
]


def redact_secrets(value: object) -> str:
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda m: f"{m.group(1)}<redacted>", text)
        else:
            text = pattern.sub("<redacted>", text)
    return text


def redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<invalid-url>"
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return urlunsplit((parts.scheme, host + port, redact_secrets(parts.path), "", ""))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def secure_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def validate_zip_member(name: str) -> PurePosixPath:
    if "\\" in name:
        raise ValueError(f"Backslash is not allowed in archive path: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts:
        raise ValueError(f"Absolute or empty archive path: {name}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe archive path: {name}")
    if ":" in path.parts[0]:
        raise ValueError(f"Drive-qualified archive path: {name}")
    return path
