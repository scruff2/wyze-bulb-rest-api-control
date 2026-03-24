$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$targets = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*wyze_light_api.py*" -and $_.CommandLine -like "*$projectRoot*"
}

if (-not $targets) {
    Write-Output "No matching wyze_light_api.py process found."
    exit 0
}

$targets | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force
    [pscustomobject]@{
        StoppedProcessId = $_.ProcessId
    }
}
