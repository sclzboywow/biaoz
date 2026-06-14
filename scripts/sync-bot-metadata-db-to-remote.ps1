param(
    [string]$RemoteHost = "111.231.22.77",
    [string]$RemoteUser = "ubuntu",
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\id_ed25519",
    [string]$RemoteDbName = "biaoz",
    [string]$RemoteDbUser = "biaoz",
    [string]$RemoteDbPassword = "biaoz",
    [switch]$SkipExport,
    [string]$DumpFile = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path $repoRoot "backend"
$exportScript = Join-Path $backend "scripts\export_bot_metadata_db.py"
$python = Join-Path $backend ".venv\Scripts\python.exe"
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Test-Path $IdentityFile)) {
    throw "SSH key not found: $IdentityFile"
}
if (-not (Test-Path $python)) {
    throw "python venv not found: $python"
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

Write-Host "QQ bot slim metadata sync (search + baidu share only)"
Write-Host "Tables: standard_resources (slim), documents, document_versions (current)"

if (-not $SkipExport) {
    Write-Host "[1/5] export slim bot dump locally ..."
    if ($DryRun) {
        Write-Host "dry-run: $python $exportScript"
    } else {
        & $python $exportScript
        if ($LASTEXITCODE -ne 0) { throw "export_bot_metadata_db.py failed" }
        $DumpFile = (Get-ChildItem -Path (Join-Path $logDir "biaoz-bot-metadata-*.sql") | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
    }
} elseif ([string]::IsNullOrWhiteSpace($DumpFile)) {
    $latest = Get-ChildItem -Path (Join-Path $logDir "biaoz-bot-metadata-*.sql") | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $latest) { throw "no bot dump found under $logDir" }
    $DumpFile = $latest.FullName
    Write-Host "reuse dump: $DumpFile"
}

if (-not $DryRun -and -not (Test-Path $DumpFile)) {
    throw "dump file not found: $DumpFile"
}

$sizeMb = if ($DryRun) { "?" } else { [math]::Round((Get-Item $DumpFile).Length / 1MB, 1) }
Write-Host "dump: $DumpFile (${sizeMb} MB)"

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$remoteDump = "/tmp/biaoz-bot-metadata-$timestamp.sql"

Write-Host "[2/5] test SSH $remote ..."
if ($DryRun) {
    Write-Host "dry-run: ssh $remote echo ok"
} else {
    Invoke-Ssh "echo connected user=\$(whoami) host=\$(hostname)"
}

Write-Host "[3/5] upload dump -> ${remote}:$remoteDump"
if ($DryRun) {
    Write-Host "dry-run: scp $DumpFile ${remote}:$remoteDump"
} else {
    & scp @sshBase $DumpFile "${remote}:$remoteDump"
    if ($LASTEXITCODE -ne 0) { throw "scp failed" }
}

$restoreScript = @'
set -euo pipefail
export PGPASSWORD='biaoz'
sudo -u postgres psql -v ON_ERROR_STOP=1 -c 'DROP DATABASE IF EXISTS biaoz WITH (FORCE);'
sudo -u postgres psql -v ON_ERROR_STOP=1 -c 'CREATE DATABASE biaoz OWNER biaoz;'
sed -e '/^SET transaction_timeout/d' -e '/^\\restrict /d' -e '/^\\unrestrict /d' -e '/^CREATE SCHEMA public;/d' REMOTE_DUMP | psql -h localhost -U biaoz -d biaoz -v ON_ERROR_STOP=1 -f -
echo restore_ok
rm -f REMOTE_DUMP
'@ -replace 'REMOTE_DUMP', $remoteDump

Write-Host "[4/5] restore slim bot db on remote ..."
if ($DryRun) {
    Write-Host "dry-run restore on remote"
} else {
    Invoke-Ssh $restoreScript
}

Write-Host "[5/5] verify remote row counts"
$verify = @'
export PGPASSWORD='biaoz'
psql -h localhost -U biaoz -d biaoz -Atc "SELECT 'standard_resources='||count(*) FROM standard_resources;"
psql -h localhost -U biaoz -d biaoz -Atc "SELECT 'documents='||count(*) FROM documents;"
psql -h localhost -U biaoz -d biaoz -Atc "SELECT 'document_versions='||count(*) FROM document_versions;"
psql -h localhost -U biaoz -d biaoz -Atc "SELECT pg_size_pretty(pg_database_size('biaoz'));"
'@
if ($DryRun) {
    Write-Host "dry-run verify"
} else {
    Invoke-Ssh $verify
}

Write-Host "done. bot slim dump kept at: $DumpFile"
