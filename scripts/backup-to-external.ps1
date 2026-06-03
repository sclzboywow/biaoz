$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path $root "backend"
$localStorage = Join-Path $backend "data\standard-docs"
$externalRoot = $env:BACKUP_EXTERNAL_ROOT
if (-not $externalRoot) {
  $externalRoot = "G:\data\biao-zhun-backup"
}

if (-not (Test-Path -LiteralPath (Split-Path $externalRoot -Qualifier))) {
  Write-Host "External drive is not available: $externalRoot"
  exit 0
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$fileBackup = Join-Path $externalRoot "standard-docs"
$dbBackupDir = Join-Path $externalRoot "postgres"
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -LiteralPath $fileBackup, $dbBackupDir, $logDir | Out-Null

$pgDump = "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe"
if (-not (Test-Path -LiteralPath $pgDump)) {
  $pgDump = "C:\Program Files\PostgreSQL\17\pgAdmin 4\runtime\pg_dump.exe"
}
if (-not (Test-Path -LiteralPath $pgDump)) {
  throw "pg_dump.exe not found."
}

$env:PGPASSWORD = $env:POSTGRES_PASSWORD
if (-not $env:PGPASSWORD) {
  $env:PGPASSWORD = "biaoz"
}
$dbFile = Join-Path $dbBackupDir "biaoz-$timestamp.dump"
& $pgDump --host localhost --port 5432 --username biaoz --format custom --file $dbFile biaoz
if ($LASTEXITCODE -ne 0) {
  throw "pg_dump failed with exit code $LASTEXITCODE"
}

if (Test-Path -LiteralPath $localStorage) {
  $copyLog = Join-Path $logDir "backup-to-external.log"
  robocopy $localStorage $fileBackup /E /XO /FFT /R:1 /W:1 /MT:8 /NP /LOG:$copyLog
  $copyCode = $LASTEXITCODE
  if ($copyCode -gt 7) {
    throw "robocopy failed with exit code $copyCode"
  }
}

Write-Host "Backup completed."
Write-Host "Database: $dbFile"
Write-Host "Files: $fileBackup"
