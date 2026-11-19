@echo off
rem Start OKR Drum from source: uses .venv (install_windows.bat) or a conda env called "okrdrum".
cd /d "%~dp0"
set "PYW="
if exist ".venv\Scripts\pythonw.exe" set "PYW=.venv\Scripts\pythonw.exe"
for %%D in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\anaconda3" "%LOCALAPPDATA%\miniconda3" "%ProgramData%\miniconda3") do (
    if not defined PYW if exist "%%~D\envs\okrdrum\pythonw.exe" set "PYW=%%~D\envs\okrdrum\pythonw.exe"
)
if not defined PYW (
    echo OKR Drum is not installed yet - run install_windows.bat, or make the conda env "okrdrum".
    pause
    exit /b 1
)
if /i "%1"=="debug" (
    rem "run_windows.bat debug" keeps a console open so error messages stay visible
    "%PYW:pythonw.exe=python.exe%" okr_drum.py
    pause
) else (
    start "" "%PYW%" okr_drum.py
)
