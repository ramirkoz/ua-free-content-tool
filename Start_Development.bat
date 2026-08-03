@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "PY_CMD=python"
where py >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3"

%PY_CMD% -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>nul
if errorlevel 1 goto no_python

%PY_CMD% -c "import cryptography" >nul 2>nul
if errorlevel 1 (
  %PY_CMD% -m pip install --disable-pip-version-check --no-input -r requirements.txt
  if errorlevel 1 goto failed
)

%PY_CMD% app.py
if errorlevel 1 goto failed
exit /b 0

:no_python
echo Python 3.11-3.13 with Tkinter is required.
echo Install 64-bit Python from python.org and enable Add Python to PATH.
pause
exit /b 1

:failed
echo.
echo The application could not be started.
echo Check the safe log in the Data\logs folder for portable mode.
pause
exit /b 1
