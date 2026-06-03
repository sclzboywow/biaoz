param(
  [switch]$Background,
  [switch]$Stop,
  [switch]$Status,
  [switch]$Once,
  [switch]$IncludeFiles,
  [int]$MaxPages = 0,
  [int]$IntervalSeconds = 30,
  [double]$RequestDelaySeconds = 1,
  [int]$PageSize = 200,
  [int]$CooldownSeconds = 1800
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path $root "backend"
$logs = Join-Path $root "logs"
$python = Join-Path $backend ".venv\Scripts\python.exe"
$worker = Join-Path $PSScriptRoot "sync_guojiabiaozhun.py"
$pidFile = Join-Path $logs "guojiabiaozhun-sync.pid"
$outLog = Join-Path $logs "guojiabiaozhun-sync.log"
$errLog = Join-Path $logs "guojiabiaozhun-sync.err.log"

New-Item -ItemType Directory -Force $logs | Out-Null

function Get-WorkerPid {
  if (-not (Test-Path $pidFile)) { return $null }
  $raw = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
  if (-not $raw) { return $null }
  try { return [int]$raw.Trim() } catch { return $null }
}

if (-not (Test-Path $python)) {
  throw "Backend virtualenv missing. Run scripts\setup-local.ps1 first."
}

if ($Stop) {
  $workerPid = Get-WorkerPid
  if ($workerPid -and (Get-Process -Id $workerPid -ErrorAction SilentlyContinue)) {
    Stop-Process -Id $workerPid -Force
    Write-Host "Stopped guojiabiaozhun sync PID: $workerPid"
  } else {
    Write-Host "guojiabiaozhun sync is not running."
  }
  Remove-Item -Force $pidFile -ErrorAction SilentlyContinue
  exit 0
}

if ($Status) {
  $workerPid = Get-WorkerPid
  if ($workerPid -and (Get-Process -Id $workerPid -ErrorAction SilentlyContinue)) {
    Write-Host "guojiabiaozhun sync is running. PID: $workerPid"
  } else {
    Write-Host "guojiabiaozhun sync is not running."
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
if ($Once) { $workerArgs += "--once" }
if ($IncludeFiles) { $workerArgs += "--include-files" }
if ($MaxPages -gt 0) { $workerArgs += @("--max-pages", "$MaxPages") }

if ($Background) {
  $existingPid = Get-WorkerPid
  if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
    Write-Host "guojiabiaozhun sync is already running. PID: $existingPid"
    Write-Host "Log: $outLog"
    exit 0
  }

  $psArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $PSCommandPath,
    "-IntervalSeconds", "$IntervalSeconds",
    "-RequestDelaySeconds", "$RequestDelaySeconds",
    "-PageSize", "$PageSize",
    "-CooldownSeconds", "$CooldownSeconds"
  )
  if ($IncludeFiles) { $psArgs += "-IncludeFiles" }
  if ($Once) { $psArgs += "-Once" }
  if ($MaxPages -gt 0) { $psArgs += @("-MaxPages", "$MaxPages") }

  $process = Start-Process -FilePath "powershell.exe" `
    -ArgumentList $psArgs `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -PassThru
  Write-Host "Started guojiabiaozhun sync launcher PID: $($process.Id)"
  Write-Host "Log: $outLog"
  Write-Host "Error log: $errLog"
  exit 0
}

$env:GUOJIA_REQUEST_DELAY_SECONDS = "$RequestDelaySeconds"
$env:GUOJIA_PAGE_SIZE = "$PageSize"
$env:GUOJIA_RATE_LIMIT_COOLDOWN_SECONDS = "$CooldownSeconds"

Push-Location $backend
try {
  & $python $workerArgs
} finally {
  Pop-Location
}
