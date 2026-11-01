# Verify an MP4 with FFprobe using the service's binary auto-discovery.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\verify_artifact.ps1 `
#     downloads\ph_scale.mp4 [-MinDuration 10]
[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [string]$Path,

    [Parameter(Position = 1)]
    [double]$MinDuration = 10.0
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
if (Test-Path (Join-Path $RootDir ".venv\Scripts\python.exe")) {
    $Python = Join-Path $RootDir ".venv\Scripts\python.exe"
}
elseif (Test-Path (Join-Path $RootDir ".venv\bin\python")) {
    $Python = Join-Path $RootDir ".venv\bin\python"
}
elseif ($env:PYTHON) {
    $Python = $env:PYTHON
}
else {
    $Python = "python"
}

$previousPythonPath = $env:PYTHONPATH
if ($previousPythonPath) {
    $env:PYTHONPATH = "$RootDir$([System.IO.Path]::PathSeparator)$previousPythonPath"
}
else {
    $env:PYTHONPATH = $RootDir
}

Push-Location $RootDir
try {
    & $Python (Join-Path $RootDir "scripts\verify_artifact.py") $Path --min-duration $MinDuration
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
    $env:PYTHONPATH = $previousPythonPath
}

exit $exitCode
