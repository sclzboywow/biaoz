param(
    [string[]]$Categories = @("QT", "DFBZ", "TC", "QYBZ", "CN", "JJ"),
    [int]$Pages = 100,
    [int]$Workers = 2,
    [double]$Delay = 2.0,
    [int]$Retries = 3,
    [int]$CycleSleepSeconds = 600,
    [switch]$Once
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"

function Write-SpcLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] $Message"
}

Write-SpcLog "SPC advanced metadata loop starting categories=$($Categories -join ',') pages=$Pages workers=$Workers delay=$Delay retries=$Retries"

do {
    $args = @(
        (Join-Path $repoRoot "scripts\sync_spc_advanced_slices_parallel.py"),
        "--categories"
    )
    $args += $Categories
    $args += @("--pages", [string]$Pages, "--workers", [string]$Workers, "--delay", [string]$Delay, "--retries", [string]$Retries)

    Write-SpcLog "advanced metadata start"
    & $python @args
    Write-SpcLog "advanced metadata finish exit=$LASTEXITCODE"

    if ($Once) {
        break
    }
    Write-SpcLog "advanced metadata cycle complete sleep=${CycleSleepSeconds}s"
    Start-Sleep -Seconds $CycleSleepSeconds
} while ($true)

Write-SpcLog "SPC advanced metadata loop stopped"
