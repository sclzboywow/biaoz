param(
  [int]$StaleMinutes = 90,
  [int]$TimeoutSeconds = 45,
  [int]$BatchSize = 48,
  [int]$MaxWorkers = 6
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$logs = Join-Path $root "logs"
$statePath = Join-Path $logs "ingest-watchdog-state.json"
$watchdogLog = Join-Path $logs "ingest-watchdog.log"

New-Item -ItemType Directory -Force $logs | Out-Null

function Write-WatchdogLog {
  param([string]$Message)
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
  Add-Content -Path $watchdogLog -Value $line -Encoding UTF8
  Write-Host $line
}

function Get-IngestProcess {
  Get-CimInstance Win32_Process |
    Where-Object {
      $_.CommandLine -like '*download_files_to_target.py*' -or
      $_.CommandLine -like '*auto-ingest-files.ps1*'
    } |
    Where-Object {
      $_.CommandLine -notlike '*ingest-watchdog.ps1*'
    }
}

function Get-IngestSnapshot {
  $backend = Join-Path $root "backend"
  $python = Join-Path $backend ".venv\Scripts\python.exe"
  $code = @'
from pathlib import Path
from sqlalchemy import func
from app.database import SessionLocal
from app.models import Document, DocumentVersion, SystemSetting

db = SessionLocal()
try:
    setting = db.query(SystemSetting).filter(SystemSetting.key == "storage_root").first()
    root = Path(setting.value) if setting else Path("")
    docs = db.query(Document).count()
    versions = db.query(DocumentVersion).count()
    duplicate_groups = (
        db.query(DocumentVersion.url_source_id, DocumentVersion.file_hash, func.count(DocumentVersion.id))
        .group_by(DocumentVersion.url_source_id, DocumentVersion.file_hash)
        .having(func.count(DocumentVersion.id) > 1)
        .count()
    )
    missing = 0
    outside = 0
    for (file_path,) in db.query(DocumentVersion.file_path).all():
        raw = Path(file_path)
        full = raw if raw.is_absolute() else root / raw
        if not full.exists():
            missing += 1
        try:
            full.resolve().relative_to(root.resolve())
        except Exception:
            outside += 1
    print(f"storage_root={root}")
    print(f"storage_exists={root.exists()}")
    print(f"documents={docs}")
    print(f"document_versions={versions}")
    print(f"duplicate_url_hash_groups={duplicate_groups}")
    print(f"missing_version_files={missing}")
    print(f"version_files_outside_storage_root={outside}")
finally:
    db.close()
'@
  Push-Location $backend
  try {
    $output = $code | & $python -
  } finally {
    Pop-Location
  }

  $snapshot = @{}
  foreach ($line in $output) {
    $parts = $line -split "=", 2
    if ($parts.Count -eq 2) {
      $snapshot[$parts[0]] = $parts[1]
    }
  }
  return $snapshot
}

function Restart-Ingest {
  param([string]$Reason)
  Write-WatchdogLog "restart reason=$Reason"
  Get-IngestProcess | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    Write-WatchdogLog "stopped pid=$($_.ProcessId)"
  }
  Start-Sleep -Seconds 2
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "scripts\auto-ingest-files.ps1") `
    -Background `
    -TimeoutSeconds $TimeoutSeconds `
    -BatchSize $BatchSize `
    -MaxWorkers $MaxWorkers | Out-Null
}

$snapshot = Get-IngestSnapshot
$processes = @(Get-IngestProcess)
$latestOut = Get-ChildItem $logs -Filter "ingest-*.out.log" -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

$now = Get-Date
$versions = [int]$snapshot["document_versions"]
$duplicates = [int]$snapshot["duplicate_url_hash_groups"]
$missing = [int]$snapshot["missing_version_files"]
$outside = [int]$snapshot["version_files_outside_storage_root"]
$storageRoot = $snapshot["storage_root"]
$storageExists = $snapshot["storage_exists"]

$previous = $null
if (Test-Path $statePath) {
  try {
    $previous = Get-Content $statePath -Raw | ConvertFrom-Json
  } catch {
    $previous = $null
  }
}

$staleLog = $false
if ($latestOut) {
  $staleLog = (($now - $latestOut.LastWriteTime).TotalMinutes -gt $StaleMinutes)
}

$noGrowth = $false
if ($previous -and $previous.document_versions -ne $null) {
  $noGrowth = ([int]$previous.document_versions -ge $versions)
}

Write-WatchdogLog "status versions=$versions processes=$($processes.Count) storage=$storageRoot exists=$storageExists duplicate_groups=$duplicates missing=$missing outside=$outside latest_log=$($latestOut.Name) latest_log_time=$($latestOut.LastWriteTime)"

if ($duplicates -ne 0 -or $missing -ne 0 -or $outside -ne 0) {
  Write-WatchdogLog "warning data_integrity duplicate_groups=$duplicates missing=$missing outside=$outside"
}

if ($processes.Count -eq 0) {
  Restart-Ingest "process_not_running"
} elseif ($staleLog -and $noGrowth) {
  Restart-Ingest "stale_log_and_no_growth"
}

@{
  checked_at = $now.ToString("o")
  document_versions = $versions
  process_count = $processes.Count
  storage_root = $storageRoot
  latest_log = if ($latestOut) { $latestOut.FullName } else { $null }
  latest_log_time = if ($latestOut) { $latestOut.LastWriteTime.ToString("o") } else { $null }
} | ConvertTo-Json | Set-Content -Path $statePath -Encoding UTF8
