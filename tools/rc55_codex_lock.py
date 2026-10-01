from pathlib import Path

p = Path("content_agent/codex_engine_v1_4_rc28.py")
s = p.read_text(encoding="utf-8")
if "import hashlib" not in s:
    s = s.replace("import importlib\n", "import hashlib\nimport importlib\n")
marker = '_OLD_INSTALL_CODEX = legacy.install_codex\n'
lock = '''_OLD_INSTALL_CODEX = legacy.install_codex\n_CODEX_LOCKED_WHEELS = {\n    "openai_codex-0.156.1-py3-none-any.whl": "6a11313e86027dd2da00f1af475388a578a19076ae8150b0f1c305d8564c973f",\n    "openai_codex_cli_bin-0.156.1-py3-none-win_amd64.whl": "81ab68fdadf448af52736282619875e10d365d93dd7442e94925899e77b99e7d",\n}\n\n\ndef _sha256(path: Path) -> str:\n    digest = hashlib.sha256()\n    with path.open("rb") as handle:\n        for chunk in iter(lambda: handle.read(1024 * 1024), b""):\n            digest.update(chunk)\n    return digest.hexdigest()\n\n\ndef _verify_locked_download(directory: Path) -> None:\n    files = {item.name: item for item in directory.iterdir() if item.is_file()}\n    if set(files) != set(_CODEX_LOCKED_WHEELS):\n        raise CodexEngineError(\n            "Codex download не відповідає зафіксованому набору wheel-файлів; встановлення скасовано."\n        )\n    for name, expected in _CODEX_LOCKED_WHEELS.items():\n        actual = _sha256(files[name])\n        if actual.casefold() != expected:\n            raise CodexEngineError(f"Codex wheel SHA-256 не збігається: {name}")\n'''
if marker not in s:
    raise SystemExit("Codex marker not found")
s = s.replace(marker, lock)
old = '''    command = [\n        sys.executable,\n        "-m",\n        "pip",\n        "install",\n        "--disable-pip-version-check",\n        "--no-input",\n        "--target",\n        str(staging),\n        CODEX_PACKAGE,\n    ]'''
new = '''    download_dir = versions / ("." + unique + ".download")\n    download_dir.mkdir(parents=True, exist_ok=False)\n    download_command = [\n        sys.executable, "-m", "pip", "download",\n        "--disable-pip-version-check", "--no-input", "--only-binary=:all:",\n        "--dest", str(download_dir), CODEX_PACKAGE,\n    ]\n    command = [\n        sys.executable, "-m", "pip", "install",\n        "--disable-pip-version-check", "--no-input", "--no-index",\n        "--find-links", str(download_dir), "--target", str(staging), CODEX_PACKAGE,\n    ]'''
if old not in s:
    raise SystemExit("Codex install command block not found")
s = s.replace(old, new)
old2 = '''    try:\n        completed = subprocess.run(\n            command,'''
new2 = '''    try:\n        downloaded = subprocess.run(\n            download_command,\n            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,\n            encoding="utf-8", errors="replace", timeout=600, env=env,\n            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),\n        )\n        if downloaded.returncode != 0:\n            tail = "\\n".join(downloaded.stdout.splitlines()[-14:])\n            raise CodexEngineError("Не вдалося завантажити зафіксований Codex runtime.\\n" + tail)\n        _verify_locked_download(download_dir)\n        completed = subprocess.run(\n            command,'''
if old2 not in s:
    raise SystemExit("Codex subprocess block not found")
s = s.replace(old2, new2)
old3 = '''        try:\n            if staging.exists():\n                shutil.rmtree(staging, ignore_errors=True)\n        finally:\n            pass\n        raise\n\n    importlib.invalidate_caches()'''
new3 = '''        try:\n            if staging.exists():\n                shutil.rmtree(staging, ignore_errors=True)\n        finally:\n            if download_dir.exists():\n                shutil.rmtree(download_dir, ignore_errors=True)\n        raise\n    finally:\n        if download_dir.exists():\n            shutil.rmtree(download_dir, ignore_errors=True)\n\n    importlib.invalidate_caches()'''
if old3 not in s:
    raise SystemExit("Codex cleanup block not found")
s = s.replace(old3, new3)
p.write_text(s, encoding="utf-8")
print("Codex 0.156.1 SDK + win_amd64 CLI wheel hashes locked")
