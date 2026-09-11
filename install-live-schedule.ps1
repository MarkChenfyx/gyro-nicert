$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $root "run-live-daily.bat"
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment not found: $python"
}

$arguments = '/d /c ""{0}""' -f $runner
$action = New-ScheduledTaskAction -Execute $env:ComSpec -Argument $arguments -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "15:20"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName "GYRO Daily Live Replay" -Description "Capture vn.py state and run daily replay after market close" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host "Scheduled task created: GYRO Daily Live Replay"
Write-Host "Schedule: Monday-Friday at 15:20 server local time"
Write-Host "Log: $root\storage\runtime\live-daily.log"
