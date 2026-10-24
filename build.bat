@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run start.bat first to create the Python environment.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-release.txt
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean MusicDrive.spec
if errorlevel 1 goto :error
".venv\Scripts\python.exe" scripts\collect_licenses.py
if errorlevel 1 goto :error
".venv\Scripts\python.exe" scripts\package_release.py
if errorlevel 1 goto :error
echo Build ready: dist\MusicDrive-1.0.0-windows-x64.zip
pause
exit /b 0
:error
echo Build failed. See errors above.
pause
exit /b 1
