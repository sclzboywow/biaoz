param(
    [int]$FileLimit = 1000,
    [double]$FileDelay = 3.0,
    [int]$FileTimeoutSeconds = 60,
    [int]$CycleSleepSeconds = 30,
    [int]$MaxAttempts = 3,
    [switch]$Once
)

$onceArg = @()
if ($Once) { $onceArg = @("-Once") }

& (Join-Path $PSScriptRoot "run-sacinfo-portal-file-loop.ps1") `
    -Platform local `
    -FileLimit $FileLimit `
    -FileDelay $FileDelay `
    -FileTimeoutSeconds $FileTimeoutSeconds `
    -CycleSleepSeconds $CycleSleepSeconds `
    -MaxAttempts $MaxAttempts `
    @onceArg
