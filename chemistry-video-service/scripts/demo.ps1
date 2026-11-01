# Submit one chemistry video job, poll it, and download the MP4.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\demo.ps1 `
#     "How does the pH scale work?" [output.mp4]
#
# Environment:
#   API_BASE_URL (default http://127.0.0.1:8000)
#   API_KEY (optional X-API-Key)
#   POLL_TIMEOUT_SECONDS (default 900)
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Query = "How does the pH scale work?",

    [Parameter(Position = 1)]
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
# Invoke-WebRequest renders a per-chunk progress bar, which floods the console
# with "Reading web response..." noise during polling and downloads.
$ProgressPreference = "SilentlyContinue"

$RootDir = Split-Path -Parent $PSScriptRoot
$ApiBaseUrl = if ($env:API_BASE_URL) { $env:API_BASE_URL } else { "http://127.0.0.1:8000" }
$ApiBaseUrl = $ApiBaseUrl.TrimEnd("/")
$PollTimeoutSeconds = if ($env:POLL_TIMEOUT_SECONDS) { [int]$env:POLL_TIMEOUT_SECONDS } else { 900 }

function Format-JsonText {
    param([string]$Text)
    try {
        return ($Text | ConvertFrom-Json | ConvertTo-Json -Depth 10)
    }
    catch {
        return $Text
    }
}

function Write-ErrorMessage {
    param([string]$Message)
    [Console]::Error.WriteLine($Message)
}

function Invoke-ApiRequest {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Uri,
        [hashtable]$Headers = @{},
        [string]$Body = ""
    )

    $request = @{
        Uri                = $Uri
        Method             = $Method
        Headers            = $Headers
        UseBasicParsing    = $true
        TimeoutSec         = 60
        MaximumRedirection = 5
    }
    if ($Body) {
        $request["Body"] = $Body
        $request["ContentType"] = "application/json; charset=utf-8"
    }

    try {
        $response = Invoke-WebRequest @request
        return [pscustomobject]@{
            StatusCode = [int]$response.StatusCode
            Body       = [string]$response.Content
        }
    }
    catch {
        $statusCode = 0
        $response = $_.Exception.Response
        if ($response -and $response.StatusCode) {
            $statusCode = [int]$response.StatusCode
        }

        $body = ""
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $body = [string]$_.ErrorDetails.Message
        }
        elseif ($response) {
            try {
                $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
                $body = $reader.ReadToEnd()
                $reader.Dispose()
            }
            catch {
                $body = ""
            }
        }
        if (-not $body) {
            $body = $_.Exception.Message
        }

        return [pscustomobject]@{
            StatusCode = $statusCode
            Body       = $body
        }
    }
}

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

$Headers = @{}
if ($env:API_KEY) {
    $Headers["X-API-Key"] = $env:API_KEY
}

$Payload = @{ query = $Query } | ConvertTo-Json -Compress

Write-Host "Submitting: $Query"
$create = Invoke-ApiRequest -Method "POST" -Uri "$ApiBaseUrl/v1/video-jobs" -Headers $Headers -Body $Payload
if ($create.StatusCode -ne 202) {
    Write-ErrorMessage "ERROR: job creation returned HTTP $($create.StatusCode)"
    Write-ErrorMessage (Format-JsonText $create.Body)
    exit 1
}

try {
    $created = $create.Body | ConvertFrom-Json
    $jobId = [string]$created.job_id
    $conceptId = if ($created.concept_id) { [string]$created.concept_id } else { "unknown" }
}
catch {
    Write-ErrorMessage "ERROR: could not parse the job creation response."
    Write-ErrorMessage (Format-JsonText $create.Body)
    exit 1
}

if (-not $jobId) {
    Write-ErrorMessage "ERROR: the job creation response did not include a job_id."
    Write-ErrorMessage (Format-JsonText $create.Body)
    exit 1
}

Write-Host "Job ID:     $jobId"
Write-Host "Concept:    $conceptId"
Write-Host "Status URL: $ApiBaseUrl/v1/video-jobs/$jobId"
Write-Host "Polling..."

$started = Get-Date
$lastLine = ""
while ($true) {
    $statusResponse = Invoke-ApiRequest -Method "GET" -Uri "$ApiBaseUrl/v1/video-jobs/$jobId" -Headers $Headers
    if ($statusResponse.StatusCode -ne 200) {
        Write-ErrorMessage "ERROR: status request returned HTTP $($statusResponse.StatusCode)"
        Write-ErrorMessage (Format-JsonText $statusResponse.Body)
        exit 1
    }

    try {
        $job = $statusResponse.Body | ConvertFrom-Json
    }
    catch {
        Write-ErrorMessage "ERROR: could not parse the status response."
        Write-ErrorMessage (Format-JsonText $statusResponse.Body)
        exit 1
    }

    $line = "status=$($job.status) stage=$($job.stage) progress=$($job.progress)"
    if ($line -ne $lastLine) {
        Write-Host "  $line"
        $lastLine = $line
    }

    if ($job.status -eq "completed") {
        break
    }
    if ($job.status -eq "failed" -or $job.status -eq "canceled") {
        Write-ErrorMessage "ERROR: job ended with status '$($job.status)'"
        $errorCode = if ($job.error -and $job.error.code) { [string]$job.error.code } else { "UNKNOWN" }
        $errorMessage = if ($job.error -and $job.error.message) { [string]$job.error.message } else { "no error message" }
        Write-ErrorMessage "  ${errorCode}: ${errorMessage}"
        exit 1
    }

    if (((Get-Date) - $started).TotalSeconds -gt $PollTimeoutSeconds) {
        Write-ErrorMessage "ERROR: timed out after ${PollTimeoutSeconds}s"
        exit 1
    }
    Start-Sleep -Seconds 2
}

if (-not $Output) {
    $Output = Join-Path $RootDir "downloads\$jobId.mp4"
}
$Output = [System.IO.Path]::GetFullPath($Output)
$outputDir = Split-Path -Parent $Output
if ($outputDir) {
    New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
}

Write-Host "Downloading video..."
try {
    Invoke-WebRequest -Uri "$ApiBaseUrl/v1/video-jobs/$jobId/artifact/video.mp4" `
        -Headers $Headers -OutFile $Output -UseBasicParsing | Out-Null
}
catch {
    Write-ErrorMessage "ERROR: artifact download failed: $($_.Exception.Message)"
    exit 1
}

$outputBytes = (Get-Item $Output).Length
if ($outputBytes -le 0) {
    Write-ErrorMessage "ERROR: downloaded artifact is empty: $Output"
    exit 1
}

Write-Host "Artifact:   $Output"
Write-Host "Metadata:   $ApiBaseUrl/v1/video-jobs/$jobId/artifact"
exit 0
