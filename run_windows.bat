@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
start "" pythonw okr_drum.py
