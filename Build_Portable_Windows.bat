@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "PUBLIC_VERSION.txt" goto missing_version
set /p PUBLIC_VERSION=<PUBLIC_VERSION.txt
if not defined PUBLIC_VERSION goto missing_version
set "TARGET=Release\UA_FREE_Content_Tool_v%PUBLIC_VERSION%"

if exist "%TARGET%" goto target_exists

where python >nul 2>nul
if errorlevel 1 goto no_python
python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,12) else 1)" >nul 2>nul
if errorlevel 1 goto no_python

powershell.exe -NoLogo -NoProfile -File "%CD%\tools\build_signed_python_runtime.ps1"
if errorlevel 1 goto failed

if not exist "%TARGET%\UA_FREE_Content_Tool\UA_FREE_Content_Tool.exe" goto failed

echo Signed-runtime build completed: %TARGET%
exit /b 0

:target_exists
echo Target already exists. Move or delete it manually: %TARGET%
exit /b 2

:missing_version
echo PUBLIC_VERSION.txt is missing or empty.
exit /b 1

:no_python
echo Python 3.12 is required for the signed portable runtime.
exit /b 1

:failed
echo Signed-runtime build failed.
exit /b 1
