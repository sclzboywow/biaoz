param(
    [string[]]$Categories = @("QT", "DFBZ", "TC", "QYBZ", "CN", "JJ"),
    [int]$MetadataPages = 20,
    [int]$FileLimit = 100,
    [double]$FileDelay = 1.0,
    [int]$CycleSleepSeconds = 60,
    [switch]$Once
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-SpcLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] $Message"
}

function Invoke-SpcStep {
    param([string]$Name, [string[]]$StepArgs)
    Write-SpcLog "start $Name $($StepArgs -join ' ')"
    & $python @StepArgs
    $exitCode = $LASTEXITCODE
    Write-SpcLog "finish $Name exit=$exitCode"
    return $exitCode
}

Write-SpcLog "SPC continuous ingest starting categories=$($Categories -join ',') metadata_pages=$MetadataPages file_limit=$FileLimit"

try {
    & (Join-Path $repoRoot "scripts\start-spc-member-chrome.ps1") | Out-Null
    Write-SpcLog "member Chrome debug port ready"
} catch {
    Write-SpcLog "member Chrome startup/check failed: $($_.Exception.Message)"
}

do {
    foreach ($category in $Categories) {
        Invoke-SpcStep "metadata" @(
            (Join-Path $repoRoot "scripts\sync_spc_online.py"),
            "--category", $category,
            "--pages", [string]$MetadataPages,
            "--only-pending-categories"
        )

        Invoke-SpcStep "files" @(
            (Join-Path $repoRoot "scripts\batch_ingest_spc_online_files.py"),
            "--category", $category,
            "--limit", [string]$FileLimit,
            "--delay", [string]$FileDelay,
            "--timeout", "300"
        )
    }

    if ($Once) {
        break
    }
    Write-SpcLog "cycle complete sleep=${CycleSleepSeconds}s"
    Start-Sleep -Seconds $CycleSleepSeconds
} while ($true)

Write-SpcLog "SPC continuous ingest stopped"
