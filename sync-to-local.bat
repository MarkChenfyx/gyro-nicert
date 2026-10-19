@echo off
setlocal
cd /d "%~dp0"
rem Run on the server while connected by Remote Desktop with the local drive mounted.
rem Copies new or changed server data to <local gyro_nicert>\storage\server_mirror (read-only on the server side).
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
"%PY%" scripts\sync_to_local.py %*
pause
