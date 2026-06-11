param(
    [int]$ProfileLimit = 5000,
    [int]$DecisionLimit = 5000,
    [int]$OcrTaskLimit = 500,
    [int]$AlertSweepLimit = 3000,
    [int]$CycleSleepSeconds = 900,
    [switch]$Once
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$pidFile = Join-Path $logDir "governance-loop.pid"
. (Join-Path $PSScriptRoot "loop-pid-utils.ps1")
Write-LoopPidFile -Path $pidFile -ProcessId $PID

function Write-GovernanceLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] $Message"
}

Write-GovernanceLog "governance loop starting profile=$ProfileLimit decisions=$DecisionLimit ocr=$OcrTaskLimit sweep=$AlertSweepLimit sleep=${CycleSleepSeconds}s"

try {
    do {
        Write-GovernanceLog "governance batch start"
        $output = & $python (Join-Path $repoRoot "scripts\run_governance_batch.py") `
            --profile-limit $ProfileLimit `
            --decision-limit $DecisionLimit `
            --ocr-task-limit $OcrTaskLimit `
            --alert-sweep-limit $AlertSweepLimit 2>&1
        $output | ForEach-Object { Write-Output $_ }
        Write-GovernanceLog "governance batch finish exit=$LASTEXITCODE"
        if ($Once) { break }
        Write-GovernanceLog "governance cycle complete sleep=${CycleSleepSeconds}s"
        Start-Sleep -Seconds $CycleSleepSeconds
    } while ($true)
}
finally {
    Remove-LoopPidFileIfOwned -Path $pidFile -ProcessId $PID
    Write-GovernanceLog "governance loop stopped"
}
