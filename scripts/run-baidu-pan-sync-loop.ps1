param(
    [int]$Limit = 500,
    [int]$Workers = 6,
    [int]$SleepSeconds = 30,
    [ValidateSet("metadata", "download", "none")]
    [string]$VerifyMode = "metadata",
    [switch]$NoVerify,
    [switch]$AllVersions,
    [switch]$Once
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backendDir = Join-Path $repoRoot "backend"
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "baidu-pan-sync-loop.out.log"
$pidFile = Join-Path $logDir "baidu-pan-sync-loop.pid"
. (Join-Path $PSScriptRoot "loop-pid-utils.ps1")
Write-LoopPidFile -Path $pidFile -ProcessId $PID

function Write-SyncLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] $Message"
}

$python = Join-Path $backendDir ".venv\Scripts\python.exe"
$script = Join-Path $repoRoot "scripts\sync_existing_files_to_baidu_pan.py"

try {
    Write-SyncLog "baidu pan sync loop starting limit=$Limit workers=$Workers sleep=${SleepSeconds}s verify=$VerifyMode"
    do {
        $argsList = @($script, "--limit", "$Limit", "--workers", "$Workers", "--verify-mode", "$VerifyMode")
        if ($NoVerify.IsPresent) { $argsList += "--no-verify" }
        if ($AllVersions.IsPresent) { $argsList += "--all-versions" }

        Write-SyncLog "batch start"
        Push-Location $backendDir
        try {
            $output = & $python @argsList 2>&1
            $exitCode = $LASTEXITCODE
            $output | ForEach-Object { Write-SyncLog $_ }
        } finally {
            Pop-Location
        }
        Write-SyncLog "batch end exit=$exitCode"

        if ($Once) { break }
        Start-Sleep -Seconds $SleepSeconds
    } while ($true)
} finally {
    Remove-LoopPidFileIfOwned -Path $pidFile -ProcessId $PID
}

Write-SyncLog "baidu pan sync loop stopped"
