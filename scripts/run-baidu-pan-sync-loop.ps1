param(
    [int]$Limit = 500,
    [int]$Workers = 2,
    [int]$SleepSeconds = 30,
    [ValidateSet("metadata", "download", "none")]
    [string]$VerifyMode = "metadata",
    [switch]$NoVerify,
    [switch]$AllVersions
)

$ErrorActionPreference = "Continue"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backendDir = Join-Path $repoRoot "backend"
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $logDir "baidu-pan-sync-loop-$stamp.log"
$python = Join-Path $backendDir ".venv\Scripts\python.exe"
$script = Join-Path $repoRoot "scripts\sync_existing_files_to_baidu_pan.py"

"baidu_pan_sync_loop_start $(Get-Date -Format o) limit=$Limit workers=$Workers sleep_seconds=$SleepSeconds verify_mode=$VerifyMode no_verify=$($NoVerify.IsPresent) all_versions=$($AllVersions.IsPresent)" |
    Tee-Object -FilePath $logFile -Append

while ($true) {
    $argsList = @($script, "--limit", "$Limit", "--workers", "$Workers", "--verify-mode", "$VerifyMode")
    if ($NoVerify.IsPresent) {
        $argsList += "--no-verify"
    }
    if ($AllVersions.IsPresent) {
        $argsList += "--all-versions"
    }

    "baidu_pan_sync_loop_batch_start $(Get-Date -Format o)" | Tee-Object -FilePath $logFile -Append
    Push-Location $backendDir
    try {
        & $python @argsList 2>&1 | Tee-Object -FilePath $logFile -Append
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    "baidu_pan_sync_loop_batch_end $(Get-Date -Format o) exit_code=$exitCode" | Tee-Object -FilePath $logFile -Append
    Start-Sleep -Seconds $SleepSeconds
}
