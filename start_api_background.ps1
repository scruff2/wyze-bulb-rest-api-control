param(
    [string]$Host = "127.0.0.1",
    [int]$Port = 8787
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $projectRoot "local_config.json"
$logDir = Join-Path $projectRoot "logs"
$stdoutLog = Join-Path $logDir "api-stdout.log"
$stderrLog = Join-Path $logDir "api-stderr.log"

if (-not (Test-Path $configPath)) {
    throw "Missing local_config.json in $projectRoot"
}

New-Item -ItemType Directory -Force $logDir | Out-Null

$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*wyze_light_api.py*" -and $_.CommandLine -like "*$projectRoot*"
}
if ($existing) {
    throw "wyze_light_api.py already appears to be running for this project"
}

$argumentList = @(
    "-NoProfile"
    "-ExecutionPolicy"
    "Bypass"
    "-Command"
    "Set-Location '$projectRoot'; python .\wyze_light_api.py --host $Host --port $Port --config '$configPath'"
)

$process = Start-Process -FilePath "powershell.exe" -ArgumentList $argumentList -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru -WindowStyle Hidden

[pscustomobject]@{
    ProjectRoot = $projectRoot
    ProcessId = $process.Id
    Url = "http://$Host`:$Port"
    StdoutLog = $stdoutLog
    StderrLog = $stderrLog
}
