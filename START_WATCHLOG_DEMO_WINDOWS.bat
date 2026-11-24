@echo off
setlocal
title MarineSense Watch Log - TRAINING (synthetic data)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run START_WATCHLOG_WINDOWS.bat once first.
  pause
  exit /b 1
)
echo Training mode: uses a separate folder with SYNTHETIC data. The real watch log is not touched.
".venv\Scripts\python.exe" run.py --demo %*
pause
