param(
    [int]$FileLimit = 10,
    [double]$FileDelay = 3.0,
    [int]$FileTimeoutSeconds = 60,
    [int]$CycleSleepSeconds = 120,
    [int]$MaxAttempts = 3,
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
$cursorFile = Join-Path $logDir "openstd-file-loop.cursor"

function Write-OpenstdLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] $Message"
}

function Get-OpenstdCursor {
    if (-not (Test-Path $cursorFile)) { return $null }
    $value = (Get-Content -Path $cursorFile -Raw).Trim()
    if ($value -match '^\d+$') { return [int]$value }
    return $null
}

function Set-OpenstdCursor {
    param([int]$ResourceId)
    Set-Content -Path $cursorFile -Value $ResourceId -Encoding utf8
}

function Update-OpenstdCursorFromOutput {
    param([string[]]$OutputLines)
    foreach ($line in $OutputLines) {
        if ($line -notmatch '^openstd_batch_summary ') { continue }
        $payload = $line.Substring('openstd_batch_summary '.Length) | ConvertFrom-Json
        if ($null -ne $payload.last_resource_id) {
            Set-OpenstdCursor -ResourceId ([int]$payload.last_resource_id)
        }
        break
    }
}

Write-OpenstdLog "openstd GB688 file loop starting file_limit=$FileLimit timeout=$FileTimeoutSeconds"

do {
    $cursor = Get-OpenstdCursor
    $cursorArg = @()
    if ($null -ne $cursor) {
        $cursorArg = @("--start-after-resource-id", [string]$cursor)
        Write-OpenstdLog "files start limit=$FileLimit cursor=$cursor"
    } else {
        Write-OpenstdLog "files start limit=$FileLimit cursor=(none)"
    }

    $env:GB688_CAPTCHA_MAX_ATTEMPTS = [string]$MaxAttempts
    $output = & $python (Join-Path $repoRoot "scripts\batch_ingest_openstd_gb688_files.py") `
        --limit $FileLimit `
        --delay $FileDelay `
        --timeout $FileTimeoutSeconds `
        --max-attempts $MaxAttempts `
        @cursorArg 2>&1
    $output | ForEach-Object { Write-Output $_ }
    Update-OpenstdCursorFromOutput -OutputLines $output
    Write-OpenstdLog "files finish exit=$LASTEXITCODE"

    if ($Once) { break }
    Write-OpenstdLog "cycle complete sleep=${CycleSleepSeconds}s"
    Start-Sleep -Seconds $CycleSleepSeconds
} while ($true)

Write-OpenstdLog "openstd GB688 file loop stopped"
