@echo off
setlocal
title MarineSense Watch Log
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto deps
echo Creating Python environment (first run only)...
where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo Python 3.11 or newer is required. Install it from python.org, tick "Add to PATH", then run this again.
  pause
  exit /b 1
)

:deps
if exist ".venv\installed.flag" goto run
echo Installing components (first run only)...
if exist "wheels\" (
  ".venv\Scripts\python.exe" -m pip install --no-index --find-links wheels -r requirements.txt
) else (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
if errorlevel 1 (
  echo.
  echo Installation failed. Connect to the internet once, or place the offline "wheels" folder next to this file.
  pause
  exit /b 1
)
echo ok> ".venv\installed.flag"

:run
".venv\Scripts\python.exe" run.py %*
pause
