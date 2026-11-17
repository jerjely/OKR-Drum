@echo off
rem Install OKR Drum from source on Windows (alternative to the installer).
rem Needs Python 3.10-3.13 from python.org ("Add python.exe to PATH" ticked).
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -m venv .venv || goto :fail
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || goto :fail
echo.
echo Installed. Start OKR Drum with run_windows.bat
pause
exit /b 0
:fail
echo.
echo Installation failed - see the messages above.
pause
exit /b 1
