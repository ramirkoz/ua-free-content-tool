from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from . import codex_engine_v1_3 as legacy
from . import codex_engine_v1_4_rc24 as rc24

CodexEngineError = legacy.CodexEngineError
CODEX_PACKAGE = rc24.CODEX_PACKAGE

_POINTER_FILE = "codex_active.json"
_VERSIONS_DIR = "codex_versions"
_OLD_INSTALL_CODEX = legacy.install_codex


def _runtime_root() -> Path:
    path = legacy.data_dir() / "ai_runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pointer_path() -> Path:
    return _runtime_root() / _POINTER_FILE


def _legacy_dir() -> Path:
    path = _runtime_root() / "codex"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_pointer() -> Path | None:
    pointer = _pointer_path()
    if not pointer.exists():
        return None
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        raw = str(payload.get("directory", "") or "").strip()
        if not raw:
            return None
        candidate = (_runtime_root() / raw).resolve()
        root = _runtime_root().resolve()
        if candidate != root and root not in candidate.parents:
            return None
        if (candidate / "openai_codex").exists():
            return candidate
    except Exception:
        return None
    return None


def codex_extension_dir() -> Path:
    """Resolve the active Codex runtime without mutating a loaded directory.

    Existing RC27 installs continue to work from ``Data/ai_runtime/codex``.
    A successful RC28 install writes a relative pointer to a versioned,
    side-by-side directory that is picked up on the next process start.
    """
    return _read_pointer() or _legacy_dir()


def _activate_extension_dir() -> None:
    path = codex_extension_dir()
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def _package_token() -> str:
    token = CODEX_PACKAGE.split("==", 1)[-1].strip() if "==" in CODEX_PACKAGE else "current"
    return "".join(ch if ch.isalnum() or ch in {".", "-", "_"} else "_" for ch in token) or "current"


def _write_pointer(target: Path) -> None:
    root = _runtime_root().resolve()
    resolved = target.resolve()
    if root not in resolved.parents:
        raise CodexEngineError("Нова папка Codex опинилася поза локальним AI-runtime.")
    relative = resolved.relative_to(root).as_posix()
    payload = {
        "directory": relative,
        "package": CODEX_PACKAGE,
        "updated_at": int(time.time()),
    }
    pointer = _pointer_path()
    temp = pointer.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, pointer)


def _verify_install(target: Path) -> None:
    if not (target / "openai_codex").exists():
        raise CodexEngineError("Codex встановився без пакета openai_codex; staging відхилено.")
    # pydantic_core is the exact binary that RC27 tried to delete while loaded.
    # Presence is not mandatory for every future SDK build, so verify metadata or
    # package directory rather than hardcoding one wheel layout.
    metadata = list(target.glob("openai_codex-*.dist-info"))
    if not metadata:
        metadata = list(target.glob("openai_codex*.dist-info"))
    if not metadata:
        raise CodexEngineError("Codex staging не містить metadata пакета; активацію скасовано.")


def install_codex() -> str:
    """Install Codex side-by-side; never delete DLL/PYD files used by this process."""
    root = _runtime_root()
    versions = root / _VERSIONS_DIR
    versions.mkdir(parents=True, exist_ok=True)
    token = _package_token()
    unique = f"codex-{token}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    staging = versions / ("." + unique + ".tmp")
    target = versions / unique
    staging.mkdir(parents=True, exist_ok=False)

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--target",
        str(staging),
        CODEX_PACKAGE,
    ]
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            tail = "\n".join(completed.stdout.splitlines()[-14:])
            raise CodexEngineEr("Не вдалося встановити Codex у безпечний staging.\n" + tail)
        _verify_install(staging)
        staging.rename(target)
        _write_pointer(target)
    except Exception:
        try:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        finally:
            pass
        raise

    importlib.invalidate_caches()
    legacy.clear_codex_status_cache()
    loaded = "openai_codex" in sys.modules
    if not loaded:
        _activate_extension_dir()
        return "Codex встановлено side-by-side та активовано."
    return "Codex встановлено side-by-side. Перезапустіть програму, щоб активувати новий runtime."


def _patch_imported_install_references() -> None:
    """Replace `from ... import install_codex` references already loaded by Tk UI modules."""
    for module in list(sys.modules.values()):
        if module is None:
            continue
        if not str(getattr(module, "__name__", "")).startswith("content_agent"):
            continue
        try:
            if getattr(module, "install_codex", None) is _OLD_INSTALL_CODEX:
                setattr(module, "install_codex", install_codex)
        except Exception:
            continue


def install_runtime() -> None:
    """Keep RC24 live-model selection and replace only runtime storage/install mechanics."""
    rc24.install_runtime()
    legacy.codex_extension_dir = codex_extension_dir
    legacy._activate_extension_dir = _activate_extension_dir
    legacy.install_codex = install_codex
    _patch_imported_install_references()
