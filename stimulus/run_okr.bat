@echo off
REM ============================================================
REM  Double-click to run the OKR experiment in the conda env.
REM  Keep this file next to okr_gui_experiment.py.
REM ============================================================
set "ENV_NAME=okr"

cd /d "%~dp0"

REM --- find Miniconda / Anaconda ---
set "CONDA_ROOT="
for %%D in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\Miniconda3" "%LOCALAPPDATA%\miniconda3" "C:\ProgramData\miniconda3" "C:\ProgramData\Miniconda3" "%USERPROFILE%\anaconda3" "C:\ProgramData\anaconda3") do (
    if not defined CONDA_ROOT if exist "%%~D\condabin\conda.bat" set "CONDA_ROOT=%%~D"
)
if not defined CONDA_ROOT (
    echo Could not find Miniconda. Open this file in Notepad and set CONDA_ROOT by hand,
    echo e.g.  set "CONDA_ROOT=C:\Users\you\miniconda3"
    pause
    exit /b 1
)
echo Conda: %CONDA_ROOT%

REM --- activate the environment ---
call "%CONDA_ROOT%\condabin\conda.bat" activate %ENV_NAME%
if errorlevel 1 (
    echo.
    echo The conda environment "%ENV_NAME%" was not found. Create it once in the Anaconda Prompt:
    echo     conda create -n %ENV_NAME% python=3.10 -y
    echo     conda activate %ENV_NAME%
    echo     pip install psychopy PyQt6 pyserial
    pause
    exit /b 1
)

REM --- run ---
python okr_gui_experiment.py
echo.
echo Finished. Press any key to close.
pause >nul
