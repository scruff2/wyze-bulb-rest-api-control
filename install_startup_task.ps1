param(
    [string]$TaskName = "WyzeBulbRestApiControl",
    [string]$Host = "127.0.0.1",
    [int]$Port = 8787
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $projectRoot "start_api_background.ps1"

if (-not (Test-Path (Join-Path $projectRoot "local_config.json"))) {
    throw "Missing local_config.json in $projectRoot"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -Host `"$Host`" -Port $Port"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Run wyze-bulb-rest-api-control at logon" -Force | Out-Null

Write-Output "Installed scheduled task '$TaskName'."
