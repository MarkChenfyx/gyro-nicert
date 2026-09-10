@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Complete the first server installation first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "scripts\update_server.py"
if errorlevel 1 (
  echo.
  echo [ERROR] Update failed. The existing version was not started.
  pause
  exit /b 1
)
pause
