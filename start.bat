@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" scripts\dev.py %*
) else (
    python scripts\dev.py %*
)
if errorlevel 1 pause
