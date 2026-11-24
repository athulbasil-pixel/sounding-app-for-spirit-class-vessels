@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run START_WATCHLOG_WINDOWS.bat once first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt -r requirements-dev.txt
".venv\Scripts\python.exe" -m pytest -q
pause
