param(
    [string[]]$Categories = @("QT", "DFBZ", "TC", "QYBZ", "CN", "JJ"),
    [int]$Pages = 500,
    [double]$PageDelaySeconds = 0.25,
    [double]$DetailDelaySeconds = 0.0,
    [int]$CycleSleepSeconds = 30,
    [switch]$IncludeDetail,
    [switch]$Once
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:SPC_PAGE_DELAY_SECONDS = [string]$PageDelaySeconds
$env:SPC_DETAIL_DELAY_SECONDS = [string]$DetailDelaySeconds
if (-not $IncludeDetail) {
    $env:SPC_FAST_METADATA_ONLY = "1"
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"

function Write-SpcLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] $Message"
}

Write-SpcLog "SPC metadata loop starting categories=$($Categories -join ',') pages=$Pages include_detail=$IncludeDetail page_delay=$PageDelaySeconds detail_delay=$DetailDelaySeconds"

do {
    foreach ($category in $Categories) {
        Write-SpcLog "metadata start category=$category pages=$Pages"
        $args = @(
            (Join-Path $repoRoot "scripts\sync_spc_online.py"),
            "--category", $category,
            "--pages", [string]$Pages,
            "--only-pending-categories"
        )
        if (-not $IncludeDetail) {
            $args += "--no-detail"
        }
        & $python @args
        Write-SpcLog "metadata finish category=$category exit=$LASTEXITCODE"
    }
    if ($Once) {
        break
    }
    Write-SpcLog "metadata cycle complete sleep=${CycleSleepSeconds}s"
    Start-Sleep -Seconds $CycleSleepSeconds
} while ($true)

Write-SpcLog "SPC metadata loop stopped"
