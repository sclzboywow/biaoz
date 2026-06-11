param(
    [switch]$SkipFileLoops,
    [switch]$SkipVerify
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
. (Join-Path $PSScriptRoot "loop-pid-utils.ps1")

function Write-Step {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] $Message"
}

function Start-BackgroundLoop {
    param(
        [string]$Name,
        [string]$ScriptPath,
        [string[]]$ScriptArgs = @()
    )

    $outLog = Join-Path $logDir "$Name.out.log"
    $errLog = Join-Path $logDir "$Name.err.log"
    $pidFile = Join-Path $logDir "$Name.pid"

    $existingPid = Ensure-LoopPidFile -PidPath $pidFile -ScriptPath $ScriptPath
    if ($null -ne $existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        Write-Output "[$Name] already running pid=$existingPid"
        return
    }

    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $ScriptPath) + $ScriptArgs
    $procInfo = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru -WindowStyle Hidden
    Write-LoopPidFile -Path $pidFile -ProcessId $procInfo.Id
    Write-Output "[$Name] started pid=$($procInfo.Id) log=$outLog"
}

if (-not (Test-Path $python)) {
    throw "Backend virtualenv missing: $python"
}

Write-Step "step 1/6 enable ingest + storage settings"
& $python (Join-Path $repoRoot "scripts\enable_pipeline_settings.py")

Write-Step "step 2/6 start metadata + governance loops"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "scripts\run-all-metadata-loops.ps1")

Write-Step "step 3/6 start OCR worker loop"
Start-BackgroundLoop -Name "ocr-worker" -ScriptPath (Join-Path $repoRoot "scripts\run-ocr-worker-loop.ps1")

Write-Step "step 4/6 start SAMR sync worker"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "scripts\run-samr-sync-worker.ps1") -Background

if (-not $SkipFileLoops) {
    Write-Step "step 5/6 start file ingest loops + monitor"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "scripts\run-all-ingest-file-loops.ps1")
} else {
    Write-Step "step 5/6 skipped file ingest loops (SkipFileLoops)"
}

if (-not $SkipVerify) {
    Write-Step "step 6/6 verify governance pipeline (one batch + health check)"
    Start-Sleep -Seconds 5
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUNBUFFERED = "1"
    & $python (Join-Path $repoRoot "scripts\run_governance_batch.py") `
        --profile-limit 100 `
        --decision-limit 100 `
        --ocr-task-limit 50 `
        --alert-sweep-limit 500
    $healthExit = 0
    & $python (Join-Path $repoRoot "scripts\verify_pipeline_health.py")
    $healthExit = $LASTEXITCODE
    if ($healthExit -ne 0) {
        Write-Step "health check reported issues (see pipeline_health output)"
    }
}

Write-Step "full pipeline startup complete"
