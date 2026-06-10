param(
    [int]$FileLimit = 1000,
    [double]$FileDelay = 2.0,
    [int]$FileTimeoutSeconds = 60,
    [int]$CycleSleepSeconds = 30,
    [int]$MaxConsecutiveErrors = 8,
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
$cursorFile = Join-Path $logDir "qybz-file-loop.cursor"
$pidFile = Join-Path $logDir "qybz-file-loop.pid"
. (Join-Path $PSScriptRoot "loop-pid-utils.ps1")
Write-LoopPidFile -Path $pidFile -ProcessId $PID

function Write-QybzLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] $Message"
}

function Get-QybzCursor {
    if (-not (Test-Path $cursorFile)) { return $null }
    $value = (Get-Content -Path $cursorFile -Raw).Trim()
    if ($value -match '^\d+$') { return [int]$value }
    return $null
}

function Set-QybzCursor {
    param([int]$ResourceId)
    [System.IO.File]::WriteAllText($cursorFile, "$ResourceId")
}

function Update-QybzCursorFromOutput {
    param([string[]]$OutputLines)
    foreach ($line in $OutputLines) {
        if ($line -notmatch '^qybz_batch_summary ') { continue }
        $payload = $line.Substring('qybz_batch_summary '.Length) | ConvertFrom-Json
        if ($null -ne $payload.last_resource_id) {
            Set-QybzCursor -ResourceId ([int]$payload.last_resource_id)
        }
        break
    }
}

Write-QybzLog "qybz enterprise standard file loop starting file_limit=$FileLimit"

try {
do {
    $cursor = Get-QybzCursor
    $cursorArg = @()
    if ($null -ne $cursor) {
        $cursorArg = @("--start-after-resource-id", [string]$cursor)
        Write-QybzLog "files start limit=$FileLimit cursor=$cursor"
    } else {
        Write-QybzLog "files start limit=$FileLimit cursor=(none)"
    }

    $output = & $python (Join-Path $repoRoot "scripts\batch_ingest_qybz_files.py") `
        --limit $FileLimit `
        --delay $FileDelay `
        --timeout $FileTimeoutSeconds `
        --max-consecutive-errors $MaxConsecutiveErrors `
        --defer-baidu-upload `
        @cursorArg 2>&1
    $output | ForEach-Object { Write-Output $_ }
    Update-QybzCursorFromOutput -OutputLines $output
    Write-QybzLog "files finish exit=$LASTEXITCODE"

    if ($Once) { break }
    Write-QybzLog "cycle complete sleep=${CycleSleepSeconds}s"
    Start-Sleep -Seconds $CycleSleepSeconds
} while ($true)
} finally {
    Remove-LoopPidFileIfOwned -Path $pidFile -ProcessId $PID
}

Write-QybzLog "qybz enterprise standard file loop stopped"
