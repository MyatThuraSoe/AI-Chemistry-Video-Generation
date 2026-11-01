# Run all three required queries and verify every downloaded artifact.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\run_required_jobs.ps1
#
# Environment:
#   API_BASE_URL (default http://127.0.0.1:8000)
#   API_KEY (optional X-API-Key)
#   POLL_TIMEOUT_SECONDS (default 900)
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
# Keep console output readable; see the note in demo.ps1.
$ProgressPreference = "SilentlyContinue"

$RootDir = Split-Path -Parent $PSScriptRoot
$ApiBaseUrl = if ($env:API_BASE_URL) { $env:API_BASE_URL } else { "http://127.0.0.1:8000" }
$env:API_BASE_URL = $ApiBaseUrl.TrimEnd("/")

$queries = @(
    "How does the pH scale work?"
    "Why do atoms form covalent bonds?"
    "What is the difference between ionic and covalent bonding?"
)
$slugs = @("ph_scale", "covalent_bonding", "ionic_vs_covalent")

$downloadsDir = Join-Path $RootDir "downloads"
New-Item -ItemType Directory -Force -Path $downloadsDir | Out-Null

$demoScript = Join-Path $PSScriptRoot "demo.ps1"
$verifyScript = Join-Path $PSScriptRoot "verify_artifact.ps1"
$failed = $false

for ($index = 0; $index -lt $queries.Count; $index++) {
    $query = $queries[$index]
    $output = Join-Path $downloadsDir "$($slugs[$index]).mp4"
    Write-Host ""
    Write-Host "============================================================"
    Write-Host "[$($index + 1)/$($queries.Count)] $query"
    Write-Host "============================================================"

    & $demoScript -Query $query -Output $output
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: generation failed for '$query'" -ForegroundColor Red
        $failed = $true
        continue
    }

    Write-Host "Verifying $output"
    & $verifyScript -Path $output
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: artifact verification failed for $output" -ForegroundColor Red
        $failed = $true
    }
}

Write-Host ""
if ($failed) {
    Write-Host "Result: FAILED (one or more required jobs did not complete or validate)." -ForegroundColor Red
    exit 1
}

Write-Host "Result: OK"
Write-Host "Videos:"
foreach ($slug in $slugs) {
    Write-Host "  - downloads/$slug.mp4"
}
