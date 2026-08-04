@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "PUBLIC_VERSION.txt" goto missing_version
set /p PUBLIC_VERSION=<PUBLIC_VERSION.txt
if not defined PUBLIC_VERSION goto missing_version
set "TARGET=Release\UA_FREE_Content_Tool_v%PUBLIC_VERSION%"
set "BUILD_READY=.venv-build\.ready-v%PUBLIC_VERSION%"

if exist "%TARGET%" goto target_exists

set "PY_CMD=python"
python -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>nul
if errorlevel 1 (
  set "PY_CMD="
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3.13 -c "import sys" >nul 2>nul && set "PY_CMD=py -3.13"
    if not defined PY_CMD py -3.12 -c "import sys" >nul 2>nul && set "PY_CMD=py -3.12"
    if not defined PY_CMD py -3.11 -c "import sys" >nul 2>nul && set "PY_CMD=py -3.11"
  )
)

if not defined PY_CMD goto no_python
%PY_CMD% -c "import sys; print(sys.executable); print(sys.version); raise SystemExit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)"
if errorlevel 1 goto no_python

if not exist ".venv-build\Scripts\python.exe" (
  %PY_CMD% -m venv .venv-build
  if errorlevel 1 goto failed
)

if not exist "%BUILD_READY%" (
  ".venv-build\Scripts\python.exe" -m pip install --disable-pip-version-check --no-input -r requirements-build.txt
  if errorlevel 1 goto failed
  type nul > "%BUILD_READY%"
)

".venv-build\Scripts\python.exe" -m compileall -q .
if errorlevel 1 goto failed
".venv-build\Scripts\python.exe" -m pytest -q
if errorlevel 1 goto failed
".venv-build\Scripts\python.exe" tools\check_entrypoint_imports.py
if errorlevel 1 goto failed
".venv-build\Scripts\python.exe" -c "import content_agent.main"
if errorlevel 1 goto failed

".venv-build\Scripts\pyinstaller.exe" --noconfirm --clean --windowed --name UA_FREE_Content_Tool --add-data "%CD%\content_agent\data\Europe_Kyiv.tzif;content_agent\data" --add-data "%CD%\content_agent\data\README.txt;content_agent\data" --distpath "%TARGET%" --workpath build\pyinstaller --specpath build app.py
if errorlevel 1 goto failed

copy /y README.md "%TARGET%\README.md" >nul
copy /y PLATFORM_SETUP.md "%TARGET%\PLATFORM_SETUP.md" >nul
copy /y SECURITY_NOTES.md "%TARGET%\SECURITY_NOTES.md" >nul
copy /y VERSION.txt "%TARGET%\VERSION.txt" >nul
copy /y PUBLIC_VERSION.txt "%TARGET%\PUBLIC_VERSION.txt" >nul

set "APP_FOLDER=%TARGET%\UA_FREE_Content_Tool"
if not exist "%APP_FOLDER%" goto failed
type nul > "%APP_FOLDER%\portable.flag"
type nul > "%APP_FOLDER%\clean_start.flag"
if not exist "%APP_FOLDER%\Data" mkdir "%APP_FOLDER%\Data"
copy /y PORTABLE_MODE.md "%APP_FOLDER%\PORTABLE_MODE.md" >nul

echo Build completed: %TARGET%
exit /b 0

:target_exists
echo Target already exists. Move or delete it manually: %TARGET%
exit /b 2

:missing_version
echo PUBLIC_VERSION.txt is missing or empty.
exit /b 1

:no_python
echo Python 3.11-3.13 is required for this pinned PyInstaller build.
exit /b 1

:failed
echo Build failed. No existing release folder was deleted.
exit /b 1
