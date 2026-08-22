from __future__ import annotations

import ctypes
import json
import os
import secrets
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .paths import config_path, portable_key_path, portable_mode

_TEST_HEADER = b"UA_FREE_TEST_PLAINTEXT_V1\n"
_PORTABLE_HEADER = b"UA_FREE_PORTABLE_AESGCM_V1\n"
_PORTABLE_AAD = b"UA_FREE_Content_Tool_portable_config_v1"
_ENTROPY = b"UA_FREE_Content_Tool_stabilization_20260724"


class ConfigError(RuntimeError):
    pass


@dataclass(slots=True)
class AppConfig:
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""
    ollama_fallback_model: str = ""
    ui_language: str = "uk"
    learning_enabled: bool = True
    learning_examples_limit: int = 3
    facebook_enabled: bool = True
    facebook_app_id: str = ""
    facebook_app_secret: str = field(default="", repr=False)
    threads_enabled: bool = True
    threads_app_id: str = ""
    threads_app_secret: str = field(default="", repr=False)
    # Legacy shared fields are retained for encrypted-config compatibility.
    meta_app_id: str = ""
    meta_client_token: str = field(default="", repr=False)
    meta_app_secret: str = field(default="", repr=False)
    meta_user_access_token: str = field(default="", repr=False)
    meta_user_token_expires_at: str = ""
    meta_graph_version: str = "v26.0"
    facebook_pages: list[dict[str, str]] = field(default_factory=list)
    facebook_page_1_name: str = ""
    facebook_page_1_id: str = ""
    facebook_page_1_token: str = field(default="", repr=False)
    facebook_page_2_id: str = ""
    facebook_page_2_name: str = ""
    facebook_page_2_token: str = field(default="", repr=False)
    threads_user_id: str = ""
    threads_profile_name: str = ""
    threads_token: str = field(default="", repr=False)
    threads_token_expires_at: str = ""
    threads_token_refreshed_at: str = ""
    linkedin_enabled: bool = True
    linkedin_client_id: str = ""
    linkedin_author_urn: str = ""
    linkedin_profile_name: str = ""
    linkedin_token: str = field(default="", repr=False)
    linkedin_version: str = "202607"
    instagram_enabled: bool = False
    instagram_user_id: str = ""
    instagram_profile_name: str = ""
    instagram_token: str = field(default="", repr=False)
    instagram_token_expires_at: str = ""
    telegram_enabled: bool = True
    telegram_bot_token: str = field(default="", repr=False)
    telegram_chat_id: str = ""
    google_client_id: str = ""
    google_client_secret: str = field(default="", repr=False)
    google_refresh_token: str = field(default="", repr=False)
    google_account_email: str = ""
    threads_trend_search_enabled: bool = True
    auto_collect_on_start: bool = True
    publish_start_hour: int = 9
    publish_end_hour: int = 20
    publish_interval_minutes: int = 15
    request_timeout_seconds: int = 45
    ui_font_size: int = 12

    def validate(self) -> None:
        if self.ui_language not in {"uk", "en"}:
            raise ConfigError("Application language must be uk or en.")
        if not (1 <= int(self.learning_examples_limit) <= 12):
            raise ConfigError("Learning examples limit must be between 1 and 12.")
        parts = urlsplit(self.ollama_base_url)
        if parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ConfigError("Ollama URL must be a local loopback HTTP address.")
        if not (0 <= self.publish_start_hour <= 23):
            raise ConfigError("Publish start hour must be between 0 and 23.")
        if not (1 <= self.publish_end_hour <= 24):
            raise ConfigError("Publish end hour must be between 1 and 24.")
        if self.publish_start_hour >= self.publish_end_hour:
            raise ConfigError("Publish start hour must be earlier than end hour.")
        if not (15 <= self.publish_interval_minutes <= 1440):
            raise ConfigError("Publish interval must be between 15 and 1440 minutes.")
        if self.meta_graph_version and not self.meta_graph_version.startswith("v"):
            raise ConfigError("Meta Graph API version must look like vNN.N.")
        if self.linkedin_version and (len(self.linkedin_version) != 6 or not self.linkedin_version.isdigit()):
            raise ConfigError("LinkedIn-Version must use YYYYMM format.")
        if self.google_client_id and ".apps.googleusercontent.com" not in self.google_client_id:
            raise ConfigError("Google OAuth Client ID must be a Desktop app client ID.")
        if not (9 <= self.ui_font_size <= 24):
            raise ConfigError("UI font size must be between 9 and 24 points.")

    def facebook_page(self, page_id: str) -> dict[str, str] | None:
        value = str(page_id).strip()
        for row in self.facebook_pages:
            if not isinstance(row, dict):
                continue
            if str(row.get("id", "")) == value and row.get("access_token"):
                return {
                    "id": value,
                    "name": str(row.get("name", "") or value),
                    "access_token": str(row.get("access_token", "")),
                }
        return None

    def sync_legacy_facebook_slots(self) -> None:
        pages = [
            row for row in (self.facebook_page(str(item.get("id", ""))) for item in self.facebook_pages if isinstance(item, dict))
            if row is not None
        ]
        first = pages[0] if pages else None
        second = pages[1] if len(pages) > 1 else None
        self.facebook_page_1_id = first["id"] if first else ""
        self.facebook_page_1_name = first["name"] if first else ""
        self.facebook_page_1_token = first["access_token"] if first else ""
        self.facebook_page_2_id = second["id"] if second else ""
        self.facebook_page_2_name = second["name"] if second else ""
        self.facebook_page_2_token = second["access_token"] if second else ""

    def platform_ready(self, platform: str) -> bool:
        if platform == "telegram":
            return bool(self.telegram_enabled and self.telegram_bot_token and self.telegram_chat_id)
        if platform.startswith("facebook:"):
            if not self.facebook_enabled:
                return False
            page = self.facebook_page(platform.split(":", 1)[1])
            if page is not None:
                return bool(self.meta_graph_version)
            if platform == "facebook:1":
                return bool(self.facebook_page_1_id and self.facebook_page_1_token and self.meta_graph_version)
            if platform == "facebook:2":
                return bool(self.facebook_page_2_id and self.facebook_page_2_token and self.meta_graph_version)
            return False
        if platform == "threads":
            return bool(self.threads_enabled and self.threads_user_id and self.threads_token)
        if platform == "linkedin":
            return bool(self.linkedin_enabled and self.linkedin_author_urn and self.linkedin_token and self.linkedin_version)
        if platform == "instagram":
            return bool(self.instagram_enabled and self.instagram_user_id and self.instagram_token and self.meta_graph_version)
        if platform == "google_drive":
            return bool(self.google_client_id and self.google_refresh_token)
        return False

    def to_json_bytes(self) -> bytes:
        self.validate()
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True).encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> "AppConfig":
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfigError("Configuration is corrupted.") from exc
        if not isinstance(payload, dict):
            raise ConfigError("Configuration root must be an object.")
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        if set(payload) - allowed:
            raise ConfigError("Configuration contains unknown fields.")
        result = cls(**payload)
        # Migrate the v1.0 shared Meta application into independent slots.
        if not result.facebook_app_id:
            result.facebook_app_id = result.meta_app_id
        if not result.facebook_app_secret:
            result.facebook_app_secret = result.meta_app_secret
        if not result.threads_app_id:
            result.threads_app_id = result.meta_app_id
        if not result.threads_app_secret:
            result.threads_app_secret = result.meta_app_secret
        result.meta_app_id = result.facebook_app_id or result.threads_app_id or result.meta_app_id
        result.meta_app_secret = (
            result.facebook_app_secret or result.threads_app_secret or result.meta_app_secret
        )
        if not result.facebook_pages:
            legacy_pages: list[dict[str, str]] = []
            for page_id, name, token in (
                (result.facebook_page_1_id, result.facebook_page_1_name, result.facebook_page_1_token),
                (result.facebook_page_2_id, result.facebook_page_2_name, result.facebook_page_2_token),
            ):
                if page_id and token:
                    legacy_pages.append({"id": page_id, "name": name or page_id, "access_token": token})
            result.facebook_pages = legacy_pages
        result.sync_legacy_facebook_slots()
        if not result.meta_graph_version:
            result.meta_graph_version = "v26.0"
        if not result.linkedin_version:
            result.linkedin_version = "202607"
        result.validate()
        return result


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array[Any]]:
    buffer = ctypes.create_string_buffer(data)
    blob = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _protect_windows(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob, in_buffer = _blob(data)
    entropy_blob, entropy_buffer = _blob(_ENTROPY)
    out_blob = DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "UA FREE Content Tool",
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    del in_buffer, entropy_buffer
    if not ok:
        raise ConfigError(f"Windows DPAPI encryption failed: {ctypes.GetLastError()}")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _unprotect_windows(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob, in_buffer = _blob(data)
    entropy_blob, entropy_buffer = _blob(_ENTROPY)
    out_blob = DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    del in_buffer, entropy_buffer
    if not ok:
        raise ConfigError("Configuration belongs to another Windows user or is corrupted.")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    if os.name != "nt":
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _load_or_create_portable_key(path: Path) -> bytes:
    if path.exists():
        key = path.read_bytes()
        if len(key) != 32:
            raise ConfigError("Portable encryption key is corrupted.")
        return key
    key = secrets.token_bytes(32)
    _atomic_write(path, key)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


def _portable_encrypt(raw: bytes, key_path: Path) -> bytes:
    key = _load_or_create_portable_key(key_path)
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(key).encrypt(nonce, raw, _PORTABLE_AAD)
    return _PORTABLE_HEADER + nonce + encrypted


def _portable_decrypt(encrypted: bytes, key_path: Path) -> bytes:
    if not encrypted.startswith(_PORTABLE_HEADER):
        raise ConfigError("Portable configuration has an unsupported format.")
    if not key_path.exists():
        raise ConfigError("Portable configuration key is missing. Copy the whole program folder, including Data.")
    key = key_path.read_bytes()
    if len(key) != 32:
        raise ConfigError("Portable configuration key is corrupted.")
    payload = encrypted[len(_PORTABLE_HEADER) :]
    if len(payload) < 13:
        raise ConfigError("Portable configuration is truncated.")
    nonce, ciphertext = payload[:12], payload[12:]
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, _PORTABLE_AAD)
    except Exception as exc:
        raise ConfigError("Portable configuration cannot be decrypted. The key or file is corrupted.") from exc


def save_config(config: AppConfig, path: Path | None = None, *, key_path: Path | None = None) -> None:
    target = path or config_path()
    raw = config.to_json_bytes()
    use_portable = target.name == "config.portable" or (path is None and portable_mode())
    if use_portable:
        encrypted = _portable_encrypt(raw, key_path or portable_key_path())
    elif os.name == "nt":
        encrypted = _protect_windows(raw)
    elif os.environ.get("UA_FREE_TEST_PLAINTEXT_CONFIG") == "1":
        encrypted = _TEST_HEADER + raw
    else:
        raise ConfigError("This target build stores local secrets with Windows DPAPI and must run on Windows.")
    _atomic_write(target, encrypted)


def load_config(path: Path | None = None, *, key_path: Path | None = None) -> AppConfig:
    target = path or config_path()
    if not target.exists():
        # Fail closed if half of a portable pair exists. Silent reset would make
        # tokens appear to vanish after moving the folder.
        if target.name == "config.portable" and (key_path or portable_key_path()).exists():
            raise ConfigError("Portable configuration file is missing while its key exists.")
        return AppConfig()
    encrypted = target.read_bytes()
    use_portable = target.name == "config.portable" or encrypted.startswith(_PORTABLE_HEADER)
    if use_portable:
        raw = _portable_decrypt(encrypted, key_path or portable_key_path())
    elif os.name == "nt":
        raw = _unprotect_windows(encrypted)
    elif encrypted.startswith(_TEST_HEADER) and os.environ.get("UA_FREE_TEST_PLAINTEXT_CONFIG") == "1":
        raw = encrypted[len(_TEST_HEADER) :]
    else:
        raise ConfigError("Encrypted Windows configuration cannot be opened on this operating system.")
    return AppConfig.from_json_bytes(raw)
