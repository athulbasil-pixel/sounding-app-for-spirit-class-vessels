@echo off
setlocal
rem Builds installer\Output\MarineSense_WatchLog_Setup_<version>.exe
rem Needs: Python 3.12 (py -3.12) and Inno Setup 6 (winget install JRSoftware.InnoSetup).
cd /d "%~dp0"
if not exist "build\venv312\Scripts\python.exe" (
  py -3.12 -m venv build\venv312 || goto fail
  "build\venv312\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller pillow || goto fail
)
"build\venv312\Scripts\python.exe" -c "import watchlog;open('build/version.txt','w').write(watchlog.__version__)" || goto fail
set /p VER=<build\version.txt
echo Building Watch Log %VER% ...
"build\venv312\Scripts\python.exe" -m PyInstaller run.py --name WatchLog --onedir --console --noconfirm --clean ^
  --icon "%CD%\installer\watchlog.ico" ^
  --add-data "%CD%\watchlog\templates;watchlog/templates" ^
  --add-data "%CD%\watchlog\static;watchlog/static" ^
  --add-data "%CD%\docs\field_registry.yaml;docs" ^
  --collect-data fpdf ^
  --distpath "%CD%\dist" --workpath "%CD%\build\pyi" --specpath "%CD%\build" || goto fail
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
"%ISCC%" /DAppVersion=%VER% installer\WatchLog.iss || goto fail
echo.
echo Installer ready: installer\Output\MarineSense_WatchLog_Setup_%VER%.exe
pause
exit /b 0
:fail
echo Build failed.
pause
exit /b 1
