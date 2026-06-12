param(
    [int]$Pages = 50,
    [int]$Workers = 2,
    [int]$CycleSleepSeconds = 900,
    [int[]]$SourceId = @(),
    [switch]$NoDetail,
    [switch]$OnlyPendingCategories,
    [switch]$IncludeGb,
    [switch]$Once
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
. (Join-Path $PSScriptRoot "loop-log-utils.ps1")

function Write-TrustedLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] $Message"
}

Write-TrustedLog "trusted sources loop starting pages=$Pages workers=$Workers sleep=${CycleSleepSeconds}s include_gb=$($IncludeGb.IsPresent)"

while ($true) {
    $args = @(
        (Join-Path $repoRoot "scripts\sync_trusted_sources_parallel.py"),
        "--pages", [string]$Pages,
        "--workers", [string]$Workers
    )
    foreach ($id in $SourceId) {
        $args += @("--source-id", [string]$id)
    }
    if ($NoDetail.IsPresent) {
        $args += "--no-detail"
    }
    if ($OnlyPendingCategories.IsPresent) {
        $args += "--only-pending-categories"
    }
    if ($IncludeGb.IsPresent) {
        $args += "--include-gb"
    }

    Write-TrustedLog "trusted sources start"
    $output = & $python @args 2>&1
    Write-CompactLoopOutput -OutputLines $output
    Write-TrustedLog "trusted sources finish exit=$LASTEXITCODE"
    if ($Once) {
        break
    }
    Write-TrustedLog "trusted sources cycle complete sleep=${CycleSleepSeconds}s"
    Start-Sleep -Seconds $CycleSleepSeconds
}
