param(
    [Parameter(Mandatory = $false)]
    [string]$OutputRoot = "Release"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$version = (Get-Content (Join-Path $repo "PUBLIC_VERSION.txt") -Raw).Trim()
$pythonExe = (Get-Command python).Source
$pythonRoot = Split-Path $pythonExe -Parent
$targetRoot = Join-Path $repo "$OutputRoot\UA_FREE_Content_Tool_v$version"
$appRoot = Join-Path $targetRoot "UA_FREE_Content_Tool"

if (Test-Path $targetRoot) {
    Remove-Item $targetRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $appRoot | Out-Null

# Use the official pythonw.exe as the visible launcher. Its bytes are unchanged,
# so its Authenticode signature from the Python Software Foundation remains
# valid. A signed console interpreter is included only for build validation and
# is deleted before packaging.
Copy-Item (Join-Path $pythonRoot "pythonw.exe") (Join-Path $appRoot "UA_FREE_Content_Tool.exe")
Copy-Item (Join-Path $pythonRoot "python.exe") (Join-Path $appRoot "_runtime_console.exe")
foreach ($name in @("python312.dll", "python3.dll", "vcruntime140.dll", "vcruntime140_1.dll")) {
    $source = Join-Path $pythonRoot $name
    if (Test-Path $source) {
        Copy-Item $source $appRoot
    }
}

foreach ($directory in @("DLLs", "Lib", "tcl")) {
    $source = Join-Path $pythonRoot $directory
    if (-not (Test-Path $source)) {
        throw "Required Python runtime directory is missing: $source"
    }
    Copy-Item $source (Join-Path $appRoot $directory) -Recurse
}

# Remove standard-library development and test material that the application can
# never execute. This reduces package size and avoids shipping unrelated helper
# executables or thousands of test fixtures.
foreach ($relative in @(
    "Lib\test",
    "Lib\idlelib",
    "Lib\turtledemo",
    "Lib\ensurepip",
    "Lib\venv",
    "Lib\lib2to3",
    "tcl\nmake"
)) {
    $candidate = Join-Path $appRoot $relative
    if (Test-Path $candidate) {
        Remove-Item $candidate -Recurse -Force
    }
}

$targetSitePackages = Join-Path $appRoot "Lib\site-packages"
if (Test-Path $targetSitePackages) {
    Remove-Item $targetSitePackages -Recurse -Force
}
New-Item -ItemType Directory -Path $targetSitePackages | Out-Null

# Install only declared runtime dependencies into the package. Do not copy the
# runner's global site-packages, test framework, or unrelated build utilities.
& python -m pip install --disable-pip-version-check --no-compile --target $targetSitePackages -r (Join-Path $repo "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Installing runtime dependencies failed: $LASTEXITCODE"
}
if (-not (Test-Path (Join-Path $targetSitePackages "cryptography"))) {
    throw "Runtime dependency check failed: cryptography package is missing"
}
$dependencyScripts = Join-Path $targetSitePackages "bin"
if (Test-Path $dependencyScripts) {
    Remove-Item $dependencyScripts -Recurse -Force
}

Copy-Item (Join-Path $repo "content_agent") (Join-Path $appRoot "content_agent") -Recurse

# Isolated path configuration. CPython checks an executable-specific _pth file
# for renamed launchers, while some builds prefer the DLL-specific file. Write
# all applicable names so registry, PYTHONPATH, user-site and CWD injection stay
# disabled on every supported Windows host.
$isolatedPath = @"
.
DLLs
Lib
Lib\site-packages
import site
"@
foreach ($pthName in @("python312._pth", "UA_FREE_Content_Tool._pth", "_runtime_console._pth")) {
    $isolatedPath | Set-Content -Path (Join-Path $appRoot $pthName) -Encoding ascii
}

@'
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(sys.executable).resolve().parent
os.environ["UA_FREE_PORTABLE_ROOT"] = str(_ROOT)
os.environ["PYTHONNOUSERSITE"] = "1"

# Only the renamed, signed launcher starts the GUI automatically. Normal Python
# tooling inside the runtime remains inert.
if Path(sys.executable).name.casefold() == "ua_free_content_tool.exe" and len(sys.argv) == 1:
    from content_agent.main import main
    raise SystemExit(main())
'@ | Set-Content -Path (Join-Path $targetSitePackages "sitecustomize.py") -Encoding utf8

foreach ($file in @(
    "README.md", "PLATFORM_SETUP.md", "SECURITY_NOTES.md", "PORTABLE_MODE.md",
    "VERSION.txt", "PUBLIC_VERSION.txt"
)) {
    Copy-Item (Join-Path $repo $file) $appRoot
}

New-Item -ItemType File -Path (Join-Path $appRoot "portable.flag") | Out-Null
New-Item -ItemType File -Path (Join-Path $appRoot "clean_start.flag") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $appRoot "Data") | Out-Null

$launcher = Join-Path $appRoot "UA_FREE_Content_Tool.exe"
$signature = Get-AuthenticodeSignature $launcher
if ($signature.Status -ne "Valid") {
    throw "Official Python launcher signature is not valid: $($signature.Status) $($signature.StatusMessage)"
}
if ($signature.SignerCertificate.Subject -notmatch "Python Software Foundation") {
    throw "Unexpected launcher signer: $($signature.SignerCertificate.Subject)"
}

# Never ship bytecode caches generated on the build machine.
Get-ChildItem $appRoot -Directory -Recurse -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $appRoot -File -Recurse -Include "*.pyc", "*.pyo" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

Write-Host "SIGNED_RUNTIME_ROOT=$appRoot"
Write-Host "LAUNCHER_SIGNER=$($signature.SignerCertificate.Subject)"
