@echo off
setlocal
cd /d "%~dp0"
if not exist "storage\runtime" mkdir "storage\runtime"
echo.>>"storage\runtime\live-daily.log"
echo [%date% %time%] Starting daily live replay>>"storage\runtime\live-daily.log"
".venv\Scripts\python.exe" "scripts\daily_live_replay.py" >>"storage\runtime\live-daily.log" 2>&1
set "code=%errorlevel%"
echo [%date% %time%] Finished with exit code %code%>>"storage\runtime\live-daily.log"
exit /b %code%
