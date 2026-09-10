@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Please create the project .venv first. See README.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" scripts\serve.py %*
if errorlevel 1 pause
