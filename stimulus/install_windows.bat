@echo off
REM ============================================================
REM  OKR Drum - one-time setup on the stimulus PC (Windows).
REM  Creates the conda environment "okr" with PsychoPy, then a
REM  Start menu entry (and, if you want, a desktop shortcut).
REM  No admin rights needed. Requires Miniconda or Anaconda.
REM ============================================================
set "ENV_NAME=okr"
cd /d "%~dp0"

set "CONDA_ROOT="
for %%D in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\Miniconda3" "%LOCALAPPDATA%\miniconda3" "C:\ProgramData\miniconda3" "C:\ProgramData\Miniconda3" "%USERPROFILE%\anaconda3" "C:\ProgramData\anaconda3") do (
    if not defined CONDA_ROOT if exist "%%~D\condabin\conda.bat" set "CONDA_ROOT=%%~D"
)
if not defined CONDA_ROOT (
    echo Miniconda was not found. Install it first from https://docs.conda.io/projects/miniconda
    echo then run this file again.
    pause
    exit /b 1
)
echo Conda: %CONDA_ROOT%

call "%CONDA_ROOT%\condabin\conda.bat" activate %ENV_NAME% 2>nul
if errorlevel 1 (
    echo Creating the conda environment "%ENV_NAME%" ^(Python 3.10^)...
    call "%CONDA_ROOT%\condabin\conda.bat" create -n %ENV_NAME% python=3.10 -y || goto :fail
    call "%CONDA_ROOT%\condabin\conda.bat" activate %ENV_NAME% || goto :fail
)
echo Installing PsychoPy and the other packages (this can take several minutes)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || goto :fail

echo Checking the installation...
python okr_gui_experiment.py --selftest || goto :fail

REM --- Start menu entry and optional desktop shortcut ---
set "TARGET=%~dp0run_okr.bat"
set "ICON=%~dp0okr_drum.ico"
if not exist "%ICON%" set "ICON=%~dp0..\assets\icon\okr_drum.ico"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Programs')+'\OKR Drum.lnk'); $s.TargetPath='%TARGET%'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%ICON%'; $s.Save()"
echo Start menu entry "OKR Drum" created.
set /p DESK="Also put a shortcut on the desktop? [y/N] "
if /i "%DESK%"=="y" powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\OKR Drum.lnk'); $s.TargetPath='%TARGET%'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%ICON%'; $s.Save()"

echo.
echo Done. Start the experiment from the Start menu ("OKR Drum") or with run_okr.bat.
pause
exit /b 0

:fail
echo.
echo Something went wrong - see the messages above.
pause
exit /b 1
