param(
    [int]$FileLimit = 1000,
    [double]$FileDelay = 4.0,
    [int]$FileTimeoutSeconds = 60,
    [int]$CycleSleepSeconds = 30,
    [int]$MaxConsecutiveErrors = 20,
    [switch]$Once
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
if (-not $env:DATABASE_URL) {
    $env:DATABASE_URL = "postgresql+psycopg://biaoz:biaoz@127.0.0.1:5432/biaoz"
}
if (-not $env:TTBZ_CDP_URL) {
    $env:TTBZ_CDP_URL = "http://127.0.0.1:9223"
}
if (-not $env:TTBZ_HTTP_PROXY) {
    $env:TTBZ_HTTP_PROXY = "socks5://127.0.0.1:18080"
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
$jumpTunnelScript = Join-Path $repoRoot "scripts\ttbz-jump-tunnel.ps1"
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$cursorFile = Join-Path $logDir "ttbz-file-loop.cursor"
$pidFile = Join-Path $logDir "ttbz-file-loop.pid"
. (Join-Path $PSScriptRoot "loop-pid-utils.ps1")
. (Join-Path $PSScriptRoot "loop-log-utils.ps1")
Write-LoopPidFile -Path $pidFile -ProcessId $PID

function Write-TtbzLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] $Message"
}

function Get-TtbzCursor {
    if (-not (Test-Path $cursorFile)) { return $null }
    $value = (Get-Content -Path $cursorFile -Raw).Trim()
    if ($value -match '^\d+$') { return [int]$value }
    return $null
}

function Set-TtbzCursor {
    param([int]$ResourceId)
    [System.IO.File]::WriteAllText($cursorFile, "$ResourceId")
}

function Update-TtbzCursorFromOutput {
    param([string[]]$OutputLines)
    foreach ($line in $OutputLines) {
        if ($line -notmatch '^ttbz_batch_summary ') { continue }
        $payload = $line.Substring('ttbz_batch_summary '.Length) | ConvertFrom-Json
        if ($null -ne $payload.last_resource_id) {
            Set-TtbzCursor -ResourceId ([int]$payload.last_resource_id)
        }
        break
    }
}

Write-TtbzLog "ttbz group standard file loop starting file_limit=$FileLimit cdp=$env:TTBZ_CDP_URL proxy=$env:TTBZ_HTTP_PROXY"

$proxyArg = @()
try {
    $tunnelOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $jumpTunnelScript 2>&1
    $tunnelOutput | ForEach-Object { Write-TtbzLog $_ }
    $proxyUrl = ($tunnelOutput | Where-Object { $_ -match '^socks5://' } | Select-Object -Last 1)
    if ($proxyUrl) {
        $env:TTBZ_HTTP_PROXY = [string]$proxyUrl
        $proxyArg = @("--http-proxy", [string]$proxyUrl)
        Write-TtbzLog "ttbz proxy enabled via jump server: $proxyUrl"
    }
} catch {
    Write-TtbzLog "ttbz jump tunnel failed, continuing without proxy: $($_.Exception.Message)"
}

try {
    $loginCheck = & $python (Join-Path $repoRoot "scripts\check_ttbz_login.py") 2>&1
    $loginCheck | ForEach-Object { Write-TtbzLog $_ }
} catch {
    Write-TtbzLog "ttbz login check failed: $($_.Exception.Message)"
}

try {
do {
    $cursor = Get-TtbzCursor
    $cursorArg = @()
    if ($null -ne $cursor) {
        $cursorArg = @("--start-after-resource-id", [string]$cursor)
        Write-TtbzLog "files start limit=$FileLimit cursor=$cursor"
    } else {
        Write-TtbzLog "files start limit=$FileLimit cursor=(none)"
    }

    $output = & $python (Join-Path $repoRoot "scripts\batch_ingest_ttbz_files.py") `
        --limit $FileLimit `
        --delay $FileDelay `
        --timeout $FileTimeoutSeconds `
        --max-consecutive-errors $MaxConsecutiveErrors `
        --defer-baidu-upload `
        @proxyArg `
        @cursorArg 2>&1
    Write-CompactLoopOutput -OutputLines $output
    Update-TtbzCursorFromOutput -OutputLines $output
    Write-TtbzLog "files finish exit=$LASTEXITCODE"

    if ($Once) { break }
    Write-TtbzLog "cycle complete sleep=${CycleSleepSeconds}s"
    Start-Sleep -Seconds $CycleSleepSeconds
} while ($true)
} finally {
    Remove-LoopPidFileIfOwned -Path $pidFile -ProcessId $PID
}

Write-TtbzLog "ttbz group standard file loop stopped"
