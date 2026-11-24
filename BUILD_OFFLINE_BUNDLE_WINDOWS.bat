@echo off
setlocal
rem Downloads every package the Watch Log needs into .\wheels so another PC can install
rem WITHOUT internet. Run this on a PC that has internet and the SAME Python version
rem (e.g. 3.12 64-bit) as the ship's ECR PC. Then copy this whole folder (with wheels\)
rem to the ship PC and run START_WATCHLOG_WINDOWS.bat there.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -c "import sys; print('Building wheels for Python', sys.version.split()[0])"
%PY% -m pip download -r requirements.txt -d wheels --only-binary=:all:
if errorlevel 1 (
  echo.
  echo Download failed - check the internet connection.
  pause
  exit /b 1
)
echo.
echo Done. Copy this folder, including "wheels", to the ship PC.
echo The ship PC needs the same Python version installed; START_WATCHLOG_WINDOWS.bat will install from wheels offline.
pause
