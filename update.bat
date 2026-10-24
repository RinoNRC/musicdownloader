@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 goto :error

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: The local Python environment was not found.
    echo Run start.bat first, then run update.bat again.
    goto :error
)

if exist ".venv\.installed" del /q ".venv\.installed"
if exist ".venv\.installed" (
    echo ERROR: Could not remove the installation marker.
    goto :error
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt
if errorlevel 1 goto :error
copy /y requirements.txt ".venv\.installed" >nul
if errorlevel 1 goto :error

echo.
echo Update completed successfully.
pause
exit /b 0

:error
echo.
echo Update failed. See the error message above.
pause
exit /b 1
