param(
  [int]$TargetFiles = 0,
  [int]$BatchSize = 48,
  [int]$MaxWorkers = 6,
  [int]$TimeoutSeconds = 20,
  [int]$MaxAttempts = 0,
  [switch]$Background
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path $root "backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"
$script = Join-Path $root "scripts\download_files_to_target.py"
$logs = Join-Path $root "logs"

New-Item -ItemType Directory -Force $logs | Out-Null

if (-not (Test-Path $python)) {
  throw "Backend virtualenv missing. Run scripts\setup-local.ps1 first."
}

if (-not (Test-Path $script)) {
  throw "Download script missing: $script"
}

if ($TargetFiles -le 0) {
  $TargetFiles = 999999999
}

if ($MaxAttempts -le 0) {
  $MaxAttempts = 100000
}

if ($Background) {
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $outLog = Join-Path $logs "ingest-$stamp.out.log"
  $errLog = Join-Path $logs "ingest-$stamp.err.log"
  $args = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$PSCommandPath`"",
    "-TargetFiles", "$TargetFiles",
    "-BatchSize", "$BatchSize",
    "-MaxWorkers", "$MaxWorkers",
    "-TimeoutSeconds", "$TimeoutSeconds",
    "-MaxAttempts", "$MaxAttempts"
  )

  $process = Start-Process -FilePath "powershell.exe" `
    -ArgumentList $args `
    -WorkingDirectory $root `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden `
    -PassThru

  Write-Host "Started background ingest."
  Write-Host "PID: $($process.Id)"
  Write-Host "Output log: $outLog"
  Write-Host "Error log: $errLog"
  Write-Host "Check progress: powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\ingest-status.ps1"
  exit 0
}

$env:TARGET_FILES = "$TargetFiles"
$env:BATCH_SIZE = "$BatchSize"
$env:MAX_WORKERS = "$MaxWorkers"
$env:DOWNLOAD_TIMEOUT_SECONDS = "$TimeoutSeconds"
$env:MAX_ATTEMPTS = "$MaxAttempts"

Write-Host "Starting ingest..."
Write-Host "TargetFiles=$TargetFiles BatchSize=$BatchSize MaxWorkers=$MaxWorkers TimeoutSeconds=$TimeoutSeconds MaxAttempts=$MaxAttempts"
Write-Host "Storage is controlled by system settings."

& $python $script
