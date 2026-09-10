from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ...paths import data_dir


BACKEND_OPENROUTER = "openrouter"
BACKEND_ROUTER = "router"
BACKEND_AGENT = "agent"
VALID_BACKENDS = {BACKEND_OPENROUTER, BACKEND_ROUTER, BACKEND_AGENT}

_SECRET_HEADER = b"UA_FREE_OPENROUTER_AESGCM_V1\n"
_SECRET_AAD = b"UA_FREE_Content_Tool_OpenRouter_v2"


@dataclass(slots=True)
class AIBackendSettings:
    active_backend: str = BACKEND_ROUTER
    openrouter_strategy: str = "balanced"
    openrouter_monthly_budget_usd: float = 25.0
    supervisor_enabled: bool = True
    supervisor_interval_seconds: int = 60
    supervisor_summary_interval_minutes: int = 360
    supervisor_drive_root: str = "CONTENT_TOOL_SUPERVISOR"

    def normalized(self) -> "AIBackendSettings":
        backend = str(self.active_backend or BACKEND_ROUTER).strip().casefold()
        if backend not in VALID_BACKENDS:
            backend = BACKEND_ROUTER
        strategy = str(self.openrouter_strategy or "balanced").strip().casefold()
        if strategy not in {"economy", "balanced", "quality"}:
            strategy = "balanced"
        budget = max(0.0, min(10000.0, float(self.openrouter_monthly_budget_usd or 0.0)))
        interval = max(20, min(3600, int(self.supervisor_interval_seconds or 60)))
        summary = max(30, min(1440, int(self.supervisor_summary_interval_minutes or 360)))
        root = str(self.supervisor_drive_root or "CONTENT_TOOL_SUPERVISOR").strip() or "CONTENT_TOOL_SUPERVISOR"
        return AIBackendSettings(
            active_backend=backend,
            openrouter_strategy=strategy,
            openrouter_monthly_budget_usd=budget,
            supervisor_enabled=bool(self.supervisor_enabled),
            supervisor_interval_seconds=interval,
            supervisor_summary_interval_minutes=summary,
            supervisor_drive_root=root[:100],
        )


def _v2_dir() -> Path:
    path = data_dir() / "v2"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return _v2_dir() / "ai_backend.json"


def load_backend_settings() -> AIBackendSettings:
    path = settings_path()
    if not path.exists():
        return AIBackendSettings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return AIBackendSettings()
        allowed = set(AIBackendSettings.__dataclass_fields__)
        return AIBackendSettings(**{key: raw[key] for key in raw if key in allowed}).normalized()
    except Exception:
        return AIBackendSettings()


def save_backend_settings(value: AIBackendSettings) -> AIBackendSettings:
    normalized = value.normalized()
    path = settings_path()
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(asdict(normalized), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
    return normalized


def _secret_key_path() -> Path:
    return _v2_dir() / "openrouter.key"


def _secret_data_path() -> Path:
    return _v2_dir() / "openrouter.secure"


def _load_or_create_key() -> bytes:
    path = _secret_key_path()
    if path.exists():
        raw = path.read_bytes()
        if len(raw) != 32:
            raise RuntimeError("Файл ключа OpenRouter пошкоджено.")
        return raw
    raw = secrets.token_bytes(32)
    temp = path.with_suffix(".tmp")
    temp.write_bytes(raw)
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(path)
    return raw


def load_openrouter_api_key() -> str:
    path = _secret_data_path()
    if not path.exists():
        return ""
    raw = path.read_bytes()
    if not raw.startswith(_SECRET_HEADER):
        raise RuntimeError("Файл OpenRouter налаштувань пошкоджено.")
    payload = raw[len(_SECRET_HEADER):]
    if len(payload) < 13:
        raise RuntimeError("Файл OpenRouter налаштувань неповний.")
    nonce, encrypted = payload[:12], payload[12:]
    try:
        plain = AESGCM(_load_or_create_key()).decrypt(nonce, encrypted, _SECRET_AAD)
        value = json.loads(plain.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("Не вдалося розшифрувати OpenRouter API key.") from exc
    if not isinstance(value, dict):
        return ""
    return str(value.get("api_key") or "").strip()


def save_openrouter_api_key(api_key: str) -> None:
    value = str(api_key or "").strip()
    if not value:
        path = _secret_data_path()
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    plain = json.dumps({"api_key": value}, ensure_ascii=False).encode("utf-8")
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(_load_or_create_key()).encrypt(nonce, plain, _SECRET_AAD)
    path = _secret_data_path()
    temp = path.with_suffix(".tmp")
    temp.write_bytes(_SECRET_HEADER + nonce + encrypted)
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(path)
