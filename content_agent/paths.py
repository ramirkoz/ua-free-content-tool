from __future__ import annotations

import os
import stat
import sys
from functools import lru_cache
from pathlib import Path

APP_DIR = "UA_FREE_Content_Tool"
DATA_ENV = "UA_FREE_CONTENT_DATA"
PORTABLE_ROOT_ENV = "UA_FREE_PORTABLE_ROOT"
LEGACY_DATA_ENV = "UA_FREE_LEGACY_DATA_ROOT"
PORTABLE_MARKER = "portable.flag"
CLEAN_START_MARKER = "clean_start.flag"
PORTABLE_DATA_DIR = "Data"


class UnsafeDataPath(RuntimeError):
    pass


def _has_reparse_attribute(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    attrs = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & reparse)


def _reject_reparse_chain(path: Path) -> None:
    """Reject symlinks/junctions in every existing component of a data path."""
    absolute = path.expanduser().absolute()
    current = Path(absolute.anchor) if absolute.anchor else Path()
    for part in absolute.parts[1:] if absolute.anchor else absolute.parts:
        current = current / part
        if current.exists() and _has_reparse_attribute(current):
            raise UnsafeDataPath(f"Data path contains a symlink or reparse point: {current}")


def _default_base() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data)
    if os.name == "nt":
        return Path.home() / "AppData" / "Local"
    # Test/development fallback. The production target remains Windows.
    return Path.home() / ".local" / "share"


def legacy_local_data_dir() -> Path:
    """Return the pre-portable stable data directory used by R7/R8 FIX5."""
    override = os.environ.get(LEGACY_DATA_ENV)
    return Path(override).expanduser() if override else _default_base() / APP_DIR / "data"


@lru_cache(maxsize=1)
def runtime_dir() -> Path:
    override = os.environ.get(PORTABLE_ROOT_ENV)
    if override:
        return Path(override).expanduser().absolute()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # Source/development tree: app.py sits one level above content_agent.
    return Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def portable_root() -> Path | None:
    override = os.environ.get(PORTABLE_ROOT_ENV)
    root = runtime_dir()
    if override or (root / PORTABLE_MARKER).is_file():
        return root
    return None


def portable_mode() -> bool:
    # Explicit data override is reserved for tests/admin recovery and wins over
    # portable auto-detection.
    return not os.environ.get(DATA_ENV) and portable_root() is not None


@lru_cache(maxsize=1)
def data_dir() -> Path:
    override = os.environ.get(DATA_ENV)
    if override:
        target = Path(override).expanduser()
    else:
        root = portable_root()
        target = root / PORTABLE_DATA_DIR if root is not None else legacy_local_data_dir()
    _reject_reparse_chain(target.parent)
    target.mkdir(parents=True, exist_ok=True)
    _reject_reparse_chain(target)
    return target


def database_path() -> Path:
    return data_dir() / "content_agent.sqlite3"


def config_path() -> Path:
    return data_dir() / ("config.portable" if portable_mode() else "config.dpapi")


def portable_key_path() -> Path:
    return data_dir() / "portable.key"


def backups_dir() -> Path:
    path = data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def lock_path() -> Path:
    return data_dir() / "instance.lock"


def reset_path_cache_for_tests() -> None:
    runtime_dir.cache_clear()
    portable_root.cache_clear()
    data_dir.cache_clear()
