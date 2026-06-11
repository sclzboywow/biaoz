param(
    [int]$PollSeconds = 10,
    [switch]$Once
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path $repoRoot "backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$pidFile = Join-Path $logDir "ocr-worker.pid"
$outLog = Join-Path $logDir "ocr-worker.out.log"
$errLog = Join-Path $logDir "ocr-worker.err.log"
. (Join-Path $PSScriptRoot "loop-pid-utils.ps1")
Write-LoopPidFile -Path $pidFile -ProcessId $PID

function Write-OcrLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] $Message"
}

Write-OcrLog "ocr worker loop starting poll=${PollSeconds}s once=$Once"

try {
    Push-Location $backend
    $workerArgs = @("-m", "app.ocr_download_worker", "--poll-seconds", "$PollSeconds")
    if ($Once) { $workerArgs += "--once" }
    Write-OcrLog "ocr worker batch start"
    & $python @workerArgs 2>&1 | ForEach-Object { Write-Output $_ }
    Write-OcrLog "ocr worker batch finish exit=$LASTEXITCODE"
}
finally {
    Pop-Location
    Remove-LoopPidFileIfOwned -Path $pidFile -ProcessId $PID
    Write-OcrLog "ocr worker loop stopped"
}
