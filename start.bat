@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 goto :error

if exist ".venv\Scripts\python.exe" goto :check_install
if exist ".venv" (
    echo ERROR: The .venv directory exists but has no Python interpreter.
    echo Rename or remove the incomplete .venv directory and try again.
    goto :error
)

python --version >nul 2>&1
if not errorlevel 1 goto :create_python
py -3 --version >nul 2>&1
if not errorlevel 1 goto :create_py
echo ERROR: Python 3.10 or newer was not found.
echo Install Python and enable its PATH option, then try again.
goto :error

:create_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto :try_py
python -m venv ".venv"
if errorlevel 1 goto :error
goto :check_install

:try_py
py -3 --version >nul 2>&1
if errorlevel 1 goto :version_error
goto :create_py

:create_py
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto :version_error
py -3 -m venv ".venv"
if errorlevel 1 goto :error

:check_install
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto :version_error
if not exist ".venv\.installed" goto :install
fc /b requirements.txt ".venv\.installed" >nul 2>&1
if not errorlevel 1 goto :run
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
copy /y requirements.txt ".venv\.installed" >nul
if errorlevel 1 goto :error

:run
".venv\Scripts\python.exe" main.py
if errorlevel 1 goto :error
exit /b 0

:version_error
echo ERROR: Python 3.10 or newer is required.

:error
echo.
echo Startup failed. See the error message above.
pause
exit /b 1
