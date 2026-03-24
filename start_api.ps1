param(
    [string]$Host = "127.0.0.1",
    [int]$Port = 8787
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$python = "python"
$configPath = Join-Path $projectRoot "local_config.json"

if (-not (Test-Path $configPath)) {
    throw "Missing local_config.json in $projectRoot"
}

& $python ".\wyze_light_api.py" --host $Host --port $Port --config $configPath
