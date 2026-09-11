$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $root "run-live-daily.bat"
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "未找到 $python，请先完成服务器首次安装。"
}

$arguments = '/d /c ""{0}""' -f $runner
$action = New-ScheduledTaskAction -Execute $env:ComSpec -Argument $arguments -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "15:20"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName "GYRO Daily Live Replay" -Description "工作日收盘后保存 vn.py 状态并运行实盘回放对账" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host "已创建计划任务：GYRO Daily Live Replay"
Write-Host "运行时间：周一至周五 15:20（服务器本地时间）"
Write-Host "日志位置：$root\storage\runtime\live-daily.log"
