param(
    [Parameter(Mandatory = $true)][string]$TextFile,
    [Parameter(Mandatory = $true)][string]$OutputFile,
    [int]$Rate = 0,
    [string]$Voice = ""
)

$ErrorActionPreference = "Stop"

$outputDirectory = [System.IO.Path]::GetDirectoryName($OutputFile)
if ($outputDirectory -and -not (Test-Path -LiteralPath $outputDirectory)) {
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
}

Add-Type -AssemblyName System.Speech
$text = [System.IO.File]::ReadAllText($TextFile, [System.Text.Encoding]::UTF8)

$synthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synthesizer.Rate = [Math]::Max(-10, [Math]::Min(10, $Rate))
    if ($Voice) {
        try {
            $synthesizer.SelectVoice($Voice)
        } catch {
            # Fall back to the system default voice.
        }
    }
    $synthesizer.SetOutputToWaveFile($OutputFile)
    $synthesizer.Speak($text)
} finally {
    $synthesizer.Dispose()
}
