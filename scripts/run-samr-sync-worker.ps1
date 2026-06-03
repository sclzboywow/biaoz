param(
  [switch]$Background,
  [switch]$Stop,
  [switch]$Status,
  [switch]$Once,
  [int]$MaxPages = 0,
  [int]$IntervalSeconds = 120,
  [double]$RequestDelaySeconds = 5,
  [int]$CooldownSeconds = 1800
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path $root "backend"
$logs = Join-Path $root "logs"
$python = Join-Path $backend ".venv\Scripts\python.exe"
$worker = Join-Path $PSScriptRoot "samr_sync_worker.py"
$pidFile = Join-Path $logs "samr-sync-worker.pid"
$outLog = Join-Path $logs "samr-sync-worker.log"
$errLog = Join-Path $logs "samr-sync-worker.err.log"

New-Item -ItemType Directory -Force $logs | Out-Null

function Get-WorkerPid {
  if (-not (Test-Path $pidFile)) {
    return $null
  }
  $raw = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
  if (-not $raw) {
    return $null
  }
  try {
    return [int]$raw.Trim()
  } catch {
    return $null
  }
}

if (-not (Test-Path $python)) {
  throw "Backend virtualenv missing. Run scripts\setup-local.ps1 first."
}

if ($Stop) {
  $workerPid = Get-WorkerPid
  if ($workerPid) {
    $process = Get-Process -Id $workerPid -ErrorAction SilentlyContinue
    if ($process) {
      Stop-Process -Id $workerPid -Force
      Write-Host "Stopped SAMR sync worker PID: $workerPid"
    } else {
      Write-Host "SAMR sync worker PID file exists, but process is not running: $workerPid"
    }
    Remove-Item -Force $pidFile -ErrorAction SilentlyContinue
  } else {
    Write-Host "SAMR sync worker is not running."
  }
  exit 0
}

if ($Status) {
  $workerPid = Get-WorkerPid
  if ($workerPid -and (Get-Process -Id $workerPid -ErrorAction SilentlyContinue)) {
    Write-Host "SAMR sync worker is running. PID: $workerPid"
  } else {
    Write-Host "SAMR sync worker is not running."
  }
  Write-Host "Log: $outLog"
  Write-Host "Error log: $errLog"
  exit 0
}

$workerArgs = @(
  $worker,
  "--interval-seconds", "$IntervalSeconds",
  "--cooldown-seconds", "$CooldownSeconds",
  "--pid-file", "$pidFile"
)
if ($Once) {
  $workerArgs += "--once"
}
if ($MaxPages -gt 0) {
  $workerArgs += @("--max-pages", "$MaxPages")
}

if ($Background) {
  $existingPid = Get-WorkerPid
  if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
    Write-Host "SAMR sync worker is already running. PID: $existingPid"
    Write-Host "Log: $outLog"
    exit 0
  }

  $psArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $PSCommandPath,
    "-IntervalSeconds", "$IntervalSeconds",
    "-RequestDelaySeconds", "$RequestDelaySeconds",
    "-CooldownSeconds", "$CooldownSeconds"
  )
  if ($Once) {
    $psArgs += "-Once"
  }
  if ($MaxPages -gt 0) {
    $psArgs += @("-MaxPages", "$MaxPages")
  }
  $process = Start-Process -FilePath "powershell.exe" `
    -ArgumentList $psArgs `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -PassThru
  Write-Host "Started SAMR sync worker launcher PID: $($process.Id)"
  Write-Host "Log: $outLog"
  Write-Host "Error log: $errLog"
  exit 0
}

$env:SAMR_REQUEST_DELAY_SECONDS = "$RequestDelaySeconds"
$env:SAMR_RATE_LIMIT_COOLDOWN_SECONDS = "$CooldownSeconds"

Push-Location $backend
try {
  & $python $workerArgs
} finally {
  Pop-Location
}
