param(
    [string]$RemoteHost = "111.231.22.77",
    [string]$RemoteUser = "ubuntu",
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\id_ed25519",
    [ValidateSet("custom", "plain")]
    [string]$DumpFormat = "plain",
    [string]$LocalDbUrl = "postgresql+psycopg://biaoz:biaoz@localhost:5432/biaoz",
    [string]$RemoteDbName = "biaoz",
    [string]$RemoteDbUser = "biaoz",
    [string]$RemoteDbPassword = "biaoz",
    [switch]$SkipDump,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$pgBin = "C:\Program Files\PostgreSQL\17\bin"
$pgDump = Join-Path $pgBin "pg_dump.exe"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$dumpExt = if ($DumpFormat -eq "plain") { "sql" } else { "dump" }
$dumpFile = Join-Path $logDir "biaoz-metadata-$timestamp.$dumpExt"
$remoteDump = "/tmp/biaoz-metadata-$timestamp.$dumpExt"

if (-not (Test-Path $pgDump)) {
    throw "pg_dump not found: $pgDump"
}
if (-not (Test-Path $IdentityFile)) {
    throw "SSH key not found: $IdentityFile"
}

$sshBase = @(
    "-i", $IdentityFile,
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    "-o", "StrictHostKeyChecking=accept-new"
)
$remote = "${RemoteUser}@${RemoteHost}"

function Invoke-Ssh {
    param([string]$Command)
    & ssh @sshBase $remote $Command
    if ($LASTEXITCODE -ne 0) {
        throw "remote command failed: $Command"
    }
}

Write-Host "[1/5] test SSH $remote ..."
if ($DryRun) {
    Write-Host "dry-run: ssh $remote echo ok"
} else {
    Invoke-Ssh "echo connected user=\$(whoami) host=\$(hostname)"
}

if (-not $SkipDump) {
    Write-Host "[2/5] dump local metadata db -> $dumpFile"
    if ($DryRun) {
        Write-Host "dry-run: pg_dump -Fc -Z6 -f $dumpFile $LocalDbUrl"
    } else {
        $env:PGPASSWORD = "biaoz"
        if ($DumpFormat -eq "plain") {
            & $pgDump -h localhost -p 5432 -U biaoz -d biaoz --clean --if-exists --no-owner --no-privileges -f $dumpFile
        } else {
            & $pgDump -h localhost -p 5432 -U biaoz -d biaoz -Fc -Z6 -f $dumpFile
        }
        if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }
        $sizeMb = [math]::Round((Get-Item $dumpFile).Length / 1MB, 1)
        Write-Host "dump size: ${sizeMb} MB"
    }
} elseif (-not (Test-Path $dumpFile)) {
    $latest = Get-ChildItem -Path (Join-Path $logDir "biaoz-metadata-*") | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $latest) { throw "no dump file found under $logDir" }
    $dumpFile = $latest.FullName
    Write-Host "reuse dump: $dumpFile"
}

Write-Host "[3/5] upload dump -> ${remote}:$remoteDump"
if ($DryRun) {
    Write-Host "dry-run: scp $dumpFile ${remote}:$remoteDump"
} else {
    & scp @sshBase $dumpFile "${remote}:$remoteDump"
    if ($LASTEXITCODE -ne 0) { throw "scp failed" }
}

$restoreScript = @"
set -euo pipefail
export PGPASSWORD='$RemoteDbPassword'
sudo -u postgres psql -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS $RemoteDbName WITH (FORCE);"
sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE $RemoteDbName OWNER $RemoteDbUser;"
if [[ '$remoteDump' == *.sql ]]; then
  sed -e '/^SET transaction_timeout/d' -e '/^\\\\restrict /d' -e '/^\\\\unrestrict /d' '$remoteDump' | psql -h localhost -U '$RemoteDbUser' -d '$RemoteDbName' -v ON_ERROR_STOP=1 -f -
else
  if ! command -v pg_restore >/dev/null 2>&1; then
    echo 'pg_restore not found on remote host' >&2
    exit 1
  fi
  pg_restore -h localhost -U '$RemoteDbUser' -d '$RemoteDbName' --clean --if-exists --no-owner --no-privileges '$remoteDump'
fi
echo restore_ok
rm -f '$remoteDump'
"@

Write-Host "[4/5] restore on remote db=$RemoteDbName user=$RemoteDbUser"
if ($DryRun) {
    Write-Host "dry-run restore on remote"
} else {
    Invoke-Ssh $restoreScript
}

Write-Host "[5/5] verify remote row counts"
$verify = @"
export PGPASSWORD='$RemoteDbPassword'
psql -h localhost -U '$RemoteDbUser' -d '$RemoteDbName' -Atc "SELECT 'standard_resources='||count(*) FROM standard_resources;"
psql -h localhost -U '$RemoteDbUser' -d '$RemoteDbName' -Atc "SELECT 'document_versions='||count(*) FROM document_versions;"
"@
if ($DryRun) {
    Write-Host "dry-run verify"
} else {
    Invoke-Ssh $verify
}

Write-Host "done. local dump kept at: $dumpFile"
