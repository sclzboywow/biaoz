param(
    [switch]$Background,
    [switch]$Stop,
    [switch]$Status,
    [switch]$Once,
    [int]$IntervalMinutes = 30
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
$reportScript = Join-Path $repoRoot "scripts\report_ingest_stats.py"
$logDir = Join-Path $repoRoot "logs"
$pidFile = Join-Path $logDir "ingest-monitor.pid"
$outLog = Join-Path $logDir "ingest-monitor.runtime.log"
$errLog = Join-Path $logDir "ingest-monitor.err.log"
$processOutLog = Join-Path $logDir "ingest-monitor.process.out.log"
$textLog = Join-Path $logDir "ingest-monitor.log"
$jsonlLog = Join-Path $logDir "ingest-monitor.jsonl"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
. (Join-Path $PSScriptRoot "loop-pid-utils.ps1")

function Get-MonitorPid {
    return Read-LoopPidFile -Path $pidFile
}

function Write-MonitorLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $outLog -Value "[$timestamp] $Message" -Encoding utf8
}

function Invoke-IngestReport {
    & $python $reportScript `
        --interval-minutes $IntervalMinutes `
        --format both `
        --append-log $textLog `
        --append-jsonl $jsonlLog 2>&1 | ForEach-Object {
            Write-Output $_
            Add-Content -Path $outLog -Value $_ -Encoding utf8
        }
}

if (-not (Test-Path $python)) {
    throw "Backend virtualenv missing: $python"
}

if ($Stop) {
    $monitorPid = Get-MonitorPid
    if ($monitorPid -and (Get-Process -Id $monitorPid -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $monitorPid -Force
        Write-Output "Stopped ingest monitor pid=$monitorPid"
    } else {
        Write-Output "Ingest monitor is not running"
    }
    if (Test-Path $pidFile) { Remove-Item $pidFile -Force }
    exit 0
}

if ($Status) {
    $monitorPid = Get-MonitorPid
    if ($monitorPid -and (Get-Process -Id $monitorPid -ErrorAction SilentlyContinue)) {
        Write-Output "ingest monitor running pid=$monitorPid interval=${IntervalMinutes}m"
    } else {
        Write-Output "ingest monitor stopped"
    }
    if (Test-Path $textLog) {
        Write-Output "--- latest report ---"
        Get-Content -Path $textLog -Tail 12
    }
    exit 0
}

if ($Background) {
    $existing = Get-MonitorPid
    if ($existing -and (Get-Process -Id $existing -ErrorAction SilentlyContinue)) {
        Write-Output "Ingest monitor already running pid=$existing"
        exit 0
    }

    $argList = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $PSCommandPath,
        "-IntervalMinutes", [string]$IntervalMinutes
    )
    if ($Once) { $argList += "-Once" }

    $proc = Start-Process -FilePath "powershell.exe" `
        -ArgumentList $argList `
        -RedirectStandardOutput $processOutLog `
        -RedirectStandardError $errLog `
        -WindowStyle Hidden `
        -PassThru
    Write-LoopPidFile -Path $pidFile -ProcessId $proc.Id
    Write-Output "Ingest monitor started pid=$($proc.Id) interval=${IntervalMinutes}m"
    Write-Output "text log: $textLog"
    Write-Output "jsonl log: $jsonlLog"
    exit 0
}

Write-MonitorLog "ingest monitor starting interval=${IntervalMinutes}m"

do {
    Write-MonitorLog "revive dead ingest loops"
    try {
        & (Join-Path $PSScriptRoot "run-all-ingest-file-loops.ps1") | ForEach-Object { Write-MonitorLog $_ }
    } catch {
        Write-MonitorLog "revive file loops failed: $($_.Exception.Message)"
    }
    try {
        & (Join-Path $PSScriptRoot "run-all-metadata-loops.ps1") | ForEach-Object { Write-MonitorLog $_ }
    } catch {
        Write-MonitorLog "revive metadata loops failed: $($_.Exception.Message)"
    }

    Write-MonitorLog "report begin"
    try {
        Invoke-IngestReport | Out-Null
        Write-MonitorLog "report complete"
    } catch {
        Write-MonitorLog "report failed: $($_.Exception.Message)"
    }

    if ($Once) { break }

    $sleepSeconds = [Math]::Max($IntervalMinutes, 1) * 60
    Write-MonitorLog "sleep ${sleepSeconds}s"
    Start-Sleep -Seconds $sleepSeconds
} while ($true)

Write-MonitorLog "ingest monitor stopped"
