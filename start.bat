@echo off
cd /d "%~dp0"
python scripts\dev.py %*
if errorlevel 1 pause
