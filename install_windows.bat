@echo off
setlocal
rem Install OKR Drum from source on Windows (alternative to the installer).
rem Needs Python 3.10 - 3.13 from python.org.
cd /d "%~dp0"

set "PY="
for %%V in (3.12 3.13 3.11 3.10) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>nul && set "PY=python"
)
rem Miniconda / Anaconda base Python (not on PATH by default)
for %%D in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\anaconda3" "%LOCALAPPDATA%\miniconda3" "%LOCALAPPDATA%\anaconda3" "%ProgramData%\miniconda3" "%ProgramData%\anaconda3") do (
    if not defined PY if exist "%%~D\python.exe" (
        "%%~D\python.exe" -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>nul && set "PY="%%~D\python.exe""
    )
)
if not defined PY (
    echo.
    echo Python 3.10 - 3.13 was not found.
    echo Install Python 3.12 from https://www.python.org/downloads/windows/
    echo and tick "Add python.exe to PATH" in the installer, then run this again.
    goto fail
)
echo Using: %PY%
%PY% --version

if not exist ".venv\Scripts\python.exe" (
    echo Creating the environment in .venv ...
    %PY% -m venv .venv
    if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail

echo.
echo Installed. Start OKR Drum with run_windows.bat
pause
exit /b 0

:fail
echo.
echo Installation failed - see the messages above.
pause
exit /b 1
