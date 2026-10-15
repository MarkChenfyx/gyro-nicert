@echo off
setlocal
cd /d "%~dp0"
if not exist "executor\config.toml" (
    echo Please copy executor\config.example.toml to executor\config.toml and edit it first.
    pause
    exit /b 1
)
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
if not "%EXECUTOR_PYTHON%"=="" set PY=%EXECUTOR_PYTHON%
"%PY%" -m executor.runner --config executor\config.toml %*
if errorlevel 1 pause
