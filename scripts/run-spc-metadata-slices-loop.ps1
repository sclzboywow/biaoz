param(
    [string[]]$Categories = @("QT", "DFBZ", "TC", "QYBZ", "CN", "JJ"),
    [int]$Pages = 500,
    [int]$Workers = 8,
    [double]$PageDelaySeconds = 0.25,
    [int]$CycleSleepSeconds = 30,
    [switch]$IncludeDetail,
    [switch]$Once
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:SPC_PAGE_DELAY_SECONDS = [string]$PageDelaySeconds
$env:SPC_DETAIL_DELAY_SECONDS = "0"
if (-not $IncludeDetail) {
    $env:SPC_FAST_METADATA_ONLY = "1"
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
. (Join-Path $PSScriptRoot "loop-log-utils.ps1")

function Write-SpcLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] $Message"
}

Write-SpcLog "SPC sliced metadata loop starting categories=$($Categories -join ',') pages=$Pages workers=$Workers include_detail=$IncludeDetail page_delay=$PageDelaySeconds"

do {
    $args = @(
        (Join-Path $repoRoot "scripts\sync_spc_online_slices_parallel.py"),
        "--categories"
    )
    $args += $Categories
    $args += @(
        "--pages", [string]$Pages,
        "--workers", [string]$Workers,
        "--page-delay", [string]$PageDelaySeconds
    )
    if ($IncludeDetail) {
        $args += "--include-detail"
    }

    Write-SpcLog "sliced metadata start"
    $output = & $python @args 2>&1
    Write-CompactLoopOutput -OutputLines $output
    Write-SpcLog "sliced metadata finish exit=$LASTEXITCODE"

    if ($Once) {
        break
    }
    Write-SpcLog "sliced metadata cycle complete sleep=${CycleSleepSeconds}s"
    Start-Sleep -Seconds $CycleSleepSeconds
} while ($true)

Write-SpcLog "SPC sliced metadata loop stopped"
