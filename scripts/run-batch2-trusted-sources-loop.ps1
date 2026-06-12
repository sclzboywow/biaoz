param(
    [int]$Pages = 3,
    [int]$Workers = 2,
    [switch]$IncludeDisabled,
    [string[]]$AdapterKey = @()
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path $repoRoot "backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$pidFile = Join-Path $logDir "batch2-trusted-sources-loop.pid"
$outLog = Join-Path $logDir "batch2-trusted-sources-loop.out.log"
. (Join-Path $PSScriptRoot "loop-pid-utils.ps1")
Write-LoopPidFile -Path $pidFile -ProcessId $PID

function Write-Batch2Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] $Message"
    Write-Output $line
    Add-Content -Path $outLog -Value $line -Encoding UTF8
}

$argsList = @(
    (Join-Path $repoRoot "scripts\sync_batch2_trusted_sources.py"),
    "--pages", "$Pages",
    "--workers", "$Workers"
)
if ($IncludeDisabled) { $argsList += "--include-disabled" }
foreach ($key in $AdapterKey) {
    if ($key) { $argsList += @("--adapter-key", $key) }
}

Write-Batch2Log "batch2 trusted sources loop start pages=$Pages workers=$Workers includeDisabled=$IncludeDisabled"
try {
    Push-Location $backend
    & $python @argsList 2>&1 | ForEach-Object { Write-Batch2Log $_ }
    Write-Batch2Log "batch2 trusted sources loop finish exit=$LASTEXITCODE"
}
finally {
    Pop-Location
    Remove-LoopPidFileIfOwned -Path $pidFile -ProcessId $PID
}
