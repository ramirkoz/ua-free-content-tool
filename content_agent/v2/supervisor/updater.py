from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...network import fetch_url
from ...paths import data_dir, runtime_dir

_REPO = "ramirkoz/ua-free-content-tool"
_VERSION_RE = re.compile(r"^2\.0\.0-rc(?P<rc>[1-9]\d*)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_RE = re.compile(r"^[A-Za-z0-9._-]{8,96}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _rc_number(value: str) -> int:
    match = _VERSION_RE.fullmatch(str(value or "").strip())
    return int(match.group("rc")) if match else -1


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def startup_health_path() -> Path:
    return data_dir() / "supervisor" / "startup_healthy.json"


def mark_startup_healthy(version: str) -> None:
    _atomic_json(startup_health_path(), {
        "schema": "ua-free-content-tool-startup-health-v1",
        "version": str(version),
        "pid": os.getpid(),
        "healthy": True,
        "generated_at": _now_iso(),
    })


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    version: str
    url: str
    sha256: str
    name: str


@dataclass(frozen=True, slots=True)
class PreparedUpdate:
    request_id: str
    control_request_id: str
    target_version: str
    request_path: Path
    preflight_path: Path
    pending_result_path: Path
    process: subprocess.Popen[Any]


def resolve_release(target_version: str, *, current_version: str) -> ReleaseAsset:
    target = str(target_version or "").strip()
    if _rc_number(target) < 0:
        raise ValueError("UPDATE_VERSION_INVALID")
    if _rc_number(target) <= _rc_number(current_version):
        raise ValueError(f"UPDATE_NOT_NEWER: {target} <= {current_version}")
    response = fetch_url(
        f"https://api.github.com/repos/{_REPO}/releases/tags/v{target}",
        method="GET",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "UAFreeContentTool/2"},
        max_bytes=3 * 1024 * 1024,
        allowed_content_types={"application/json"},
        timeout=30,
        max_redirects=0,
        allow_http_errors=True,
    )
    if response.status != 200:
        raise RuntimeError(f"UPDATE_RELEASE_LOOKUP_HTTP_{response.status}")
    payload = response.json()
    if not isinstance(payload, dict) or str(payload.get("tag_name") or "") != f"v{target}":
        raise RuntimeError("UPDATE_RELEASE_METADATA_INVALID")
    expected_name = f"UA_FREE_Content_Tool_v{target}_Windows_Portable.zip"
    assets = payload.get("assets") if isinstance(payload.get("assets"), list) else []
    for raw in assets:
        if not isinstance(raw, dict) or str(raw.get("name") or "") != expected_name:
            continue
        url = str(raw.get("browser_download_url") or "").strip()
        digest = str(raw.get("digest") or "").strip().casefold()
        if digest.startswith("sha256:"):
            digest = digest.split(":", 1)[1]
        prefix = f"https://github.com/{_REPO}/releases/download/v{target}/"
        if not url.startswith(prefix) or not _SHA256_RE.fullmatch(digest):
            raise RuntimeError("UPDATE_RELEASE_ASSET_NOT_VERIFIABLE")
        return ReleaseAsset(target, url, digest, expected_name)
    raise RuntimeError(f"UPDATE_PORTABLE_ASSET_MISSING: {expected_name}")


def _runner_script() -> str:
    # Generated locally. Remote control selects only a validated release version;
    # it cannot inject a URL, path, executable, script or shell command.
    return r'''param([Parameter(Mandatory=$true)][string]$RequestPath)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$req = Get-Content -LiteralPath $RequestPath -Raw | ConvertFrom-Json
$root = [IO.Path]::GetFullPath([string]$req.runtime_root)
$data = Join-Path $root "Data"
$supervisor = Join-Path $data "supervisor"
$work = Join-Path $supervisor ("updates\" + [string]$req.request_id)
$zip = Join-Path $work "portable.zip"
$stage = Join-Path $work "stage"
$backup = Join-Path $work "backup"
$preflight = Join-Path $work "preflight.json"
$pending = Join-Path $supervisor "control_result_pending.json"
$health = Join-Path $supervisor "startup_healthy.json"
$applied = $false
$new = $null
$oldVersion = [string]$req.current_version
$targetVersion = [string]$req.target_version
$controlRequestId = [string]$req.control_request_id

function Write-JsonAtomic([string]$Path, [hashtable]$Payload) {
    $dir = Split-Path -Parent $Path
    if ($dir) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $tmp = "$Path.tmp"
    ($Payload | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Write-Pending([string]$State, [string]$Detail) {
    Write-JsonAtomic $pending @{
        schema = "ua-free-content-tool-control-result-v1"
        request_id = $controlRequestId
        transaction_id = [string]$req.request_id
        command = "update"
        state = $State
        detail = $Detail
        from_version = $oldVersion
        target_version = $targetVersion
        generated_at = (Get-Date).ToString("o")
    }
}

function Wait-Parent([int]$Pid, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $p = Get-Process -Id $Pid -ErrorAction SilentlyContinue
        if (-not $p) { return }
        Start-Sleep -Milliseconds 500
    }
    $p = Get-Process -Id $Pid -ErrorAction SilentlyContinue
    if ($p) { Stop-Process -Id $Pid -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 }
}

function Copy-Runtime([string]$From, [string]$To) {
    New-Item -ItemType Directory -Path $To -Force | Out-Null
    Get-ChildItem -LiteralPath $From -Force | Where-Object { $_.Name -notin @("Data", "Tools") } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $To $_.Name) -Recurse -Force
    }
}

function Clear-Runtime([string]$Root) {
    Get-ChildItem -LiteralPath $Root -Force | Where-Object { $_.Name -notin @("Data", "Tools") } | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
    }
}

try {
    New-Item -ItemType Directory -Path $work -Force | Out-Null
    Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue

    Invoke-WebRequest -Uri ([string]$req.url) -OutFile $zip -UseBasicParsing
    $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne ([string]$req.sha256).ToLowerInvariant()) { throw "UPDATE_SHA256_MISMATCH" }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($zip)
    try {
        foreach ($entry in $archive.Entries) {
            $name = [string]$entry.FullName
            $normalized = $name.Replace("\", "/")
            if ([IO.Path]::IsPathRooted($name) -or $normalized.StartsWith("/") -or $normalized.Contains("../")) {
                throw "UPDATE_ZIP_UNSAFE_PATH: $name"
            }
        }
    } finally { $archive.Dispose() }

    Expand-Archive -LiteralPath $zip -DestinationPath $stage -Force
    foreach ($required in @("UA_FREE_Content_Tool.exe", "PUBLIC_VERSION.txt", "VERSION.txt")) {
        if (-not (Test-Path -LiteralPath (Join-Path $stage $required))) { throw "UPDATE_REQUIRED_FILE_MISSING: $required" }
    }
    if ((Get-Content -LiteralPath (Join-Path $stage "PUBLIC_VERSION.txt") -Raw).Trim() -ne $targetVersion) {
        throw "UPDATE_PUBLIC_VERSION_MISMATCH"
    }
    if ((Get-Content -LiteralPath (Join-Path $stage "VERSION.txt") -Raw).Trim() -ne $targetVersion) {
        throw "UPDATE_INTERNAL_VERSION_MISMATCH"
    }

    $stagedExe = Join-Path $stage "UA_FREE_Content_Tool.exe"
    $signature = Get-AuthenticodeSignature -LiteralPath $stagedExe
    if ($signature.Status -ne "Valid") { throw ("UPDATE_LAUNCHER_SIGNATURE_INVALID: " + [string]$signature.Status) }
    if ([string]$signature.SignerCertificate.Subject -notmatch "Python Software Foundation") {
        throw ("UPDATE_LAUNCHER_SIGNER_INVALID: " + [string]$signature.SignerCertificate.Subject)
    }

    Write-JsonAtomic $preflight @{
        ready = $true
        request_id = [string]$req.request_id
        control_request_id = $controlRequestId
        target_version = $targetVersion
        generated_at = (Get-Date).ToString("o")
    }

    Wait-Parent ([int]$req.parent_pid) 45
    Copy-Runtime $root $backup
    # From this point onward the installed runtime is about to be mutated. Arm
    # rollback before the first delete/copy so a partial replacement is recoverable.
    $applied = $true
    Clear-Runtime $root
    Copy-Runtime $stage $root
    Remove-Item -LiteralPath $health -Force -ErrorAction SilentlyContinue

    $exe = Join-Path $root "UA_FREE_Content_Tool.exe"
    $new = Start-Process -FilePath $exe -WorkingDirectory $root -PassThru
    $deadline = (Get-Date).AddSeconds(100)
    $healthy = $false
    while ((Get-Date) -lt $deadline) {
        if ($new.HasExited) { break }
        if (Test-Path -LiteralPath $health) {
            try {
                $h = Get-Content -LiteralPath $health -Raw | ConvertFrom-Json
                if ([bool]$h.healthy -and [string]$h.version -eq $targetVersion) { $healthy = $true; break }
            } catch {}
        }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) { throw "UPDATE_NEW_VERSION_HEALTH_TIMEOUT" }
    Write-Pending "UPDATED" ("Portable updated and healthy; pid=" + [string]$new.Id)
    exit 0
}
catch {
    $detail = [string]$_.Exception.Message
    if ($applied -and (Test-Path -LiteralPath $backup)) {
        try {
            if ($null -ne $new -and -not $new.HasExited) {
                Stop-Process -Id $new.Id -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 1
            }
        } catch {}
        try {
            Clear-Runtime $root
            Copy-Runtime $backup $root
            Start-Process -FilePath (Join-Path $root "UA_FREE_Content_Tool.exe") -WorkingDirectory $root | Out-Null
            Write-Pending "ROLLBACK_OK" $detail
            exit 2
        } catch {
            Write-Pending "ROLLBACK_FAILED" ($detail + " | rollback: " + [string]$_.Exception.Message)
            exit 3
        }
    }
    Write-Pending "PRECHECK_FAILED" $detail
    exit 1
}
'''


def prepare_update(
    target_version: str,
    *,
    current_version: str,
    control_request_id: str = "",
) -> PreparedUpdate:
    asset = resolve_release(target_version, current_version=current_version)
    request_id = uuid.uuid4().hex
    control_id = str(control_request_id or request_id).strip()
    if not _REQUEST_RE.fullmatch(control_id):
        raise ValueError("UPDATE_CONTROL_REQUEST_ID_INVALID")
    root = data_dir() / "supervisor" / "updates" / request_id
    root.mkdir(parents=True, exist_ok=True)
    request_path = root / "request.json"
    preflight_path = root / "preflight.json"
    pending_result_path = data_dir() / "supervisor" / "control_result_pending.json"
    script_path = root / "runner.ps1"
    _atomic_json(request_path, {
        "schema": "ua-free-content-tool-update-v1",
        "request_id": request_id,
        "control_request_id": control_id,
        "current_version": str(current_version),
        "target_version": asset.version,
        "sha256": asset.sha256,
        "url": asset.url,
        "asset_name": asset.name,
        "runtime_root": str(runtime_dir()),
        "parent_pid": os.getpid(),
        "created_at": _now_iso(),
    })
    script_path.write_text(_runner_script(), encoding="utf-8")
    flags = 0
    if os.name == "nt":
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(getattr(subprocess, "DETACHED_PROCESS", 0))
    process = subprocess.Popen(
        [
            "powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(script_path), "-RequestPath", str(request_path),
        ],
        cwd=str(runtime_dir()),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=(os.name != "nt"),
    )
    return PreparedUpdate(request_id, control_id, asset.version, request_path, preflight_path, pending_result_path, process)


def wait_for_preflight(prepared: PreparedUpdate, *, timeout_seconds: int = 120) -> tuple[bool, str]:
    deadline = time.monotonic() + max(15, int(timeout_seconds))
    while time.monotonic() < deadline:
        if prepared.preflight_path.is_file():
            try:
                value = json.loads(prepared.preflight_path.read_text(encoding="utf-8-sig"))
                if isinstance(value, dict) and bool(value.get("ready")):
                    return True, "package downloaded, SHA256/signature verified and staged"
            except Exception:
                pass
        if prepared.pending_result_path.is_file():
            try:
                value = json.loads(prepared.pending_result_path.read_text(encoding="utf-8-sig"))
            except Exception:
                value = {}
            if isinstance(value, dict) and str(value.get("request_id") or "") == prepared.control_request_id:
                return False, str(value.get("detail") or value.get("state") or "update preflight failed")
        if prepared.process.poll() is not None and not prepared.preflight_path.is_file():
            return False, f"update runner exited before preflight: {prepared.process.returncode}"
        time.sleep(0.5)
    return False, "update preflight timed out"
