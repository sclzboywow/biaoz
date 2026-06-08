param(
    [string[]]$Categories = @("QT", "DFBZ", "TC", "QYBZ", "CN", "JJ"),
    [int]$FileLimit = 20,
    [double]$FileDelay = 8.0,
    [int]$FileTimeoutSeconds = 60,
    [int]$CycleSleepSeconds = 300,
    [int]$RateLimitCooldownSeconds = 1800,
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

function Get-SpcCursorPath {
    param([string]$Category)
    return Join-Path $logDir "spc-file-loop-$Category.cursor"
}

function Get-SpcCursor {
    param([string]$Category)
    $path = Get-SpcCursorPath -Category $Category
    if (-not (Test-Path $path)) {
        return $null
    }
    $value = (Get-Content -Path $path -Raw).Trim()
    if ($value -match '^\d+$') {
        return [int]$value
    }
    return $null
}

function Set-SpcCursor {
    param([string]$Category, [int]$ResourceId)
    Set-Content -Path (Get-SpcCursorPath -Category $Category) -Value $ResourceId -Encoding utf8
}

function Update-SpcCursorFromOutput {
    param([string]$Category, [string[]]$OutputLines)
    foreach ($line in $OutputLines) {
        if ($line -notmatch '^spc_batch_summary ') {
            continue
        }
        $payload = $line.Substring('spc_batch_summary '.Length) | ConvertFrom-Json
        if ($null -ne $payload.last_resource_id) {
            Set-SpcCursor -Category $Category -ResourceId ([int]$payload.last_resource_id)
        }
        break
    }
}

function Write-SpcLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] $Message"
}

Write-SpcLog "SPC file loop starting categories=$($Categories -join ',') file_limit=$FileLimit file_timeout_seconds=$FileTimeoutSeconds"

try {
    & (Join-Path $repoRoot "scripts\start-spc-member-chrome.ps1") | Out-Null
    Write-SpcLog "member Chrome debug port ready"
} catch {
    Write-SpcLog "member Chrome startup/check failed: $($_.Exception.Message)"
}

do {
    foreach ($category in $Categories) {
        $cursor = Get-SpcCursor -Category $category
        $cursorArg = @()
        if ($null -ne $cursor) {
            $cursorArg = @("--start-after-resource-id", [string]$cursor)
            Write-SpcLog "files start category=$category limit=$FileLimit cursor=$cursor"
        } else {
            Write-SpcLog "files start category=$category limit=$FileLimit cursor=(none)"
        }
        $output = & $python (Join-Path $repoRoot "scripts\batch_ingest_spc_online_files.py") --category $category --limit $FileLimit --delay $FileDelay --timeout $FileTimeoutSeconds --cooldown-on-rate-limit 0 @cursorArg 2>&1
        $output | ForEach-Object { Write-Output $_ }
        Update-SpcCursorFromOutput -Category $category -OutputLines $output
        Write-SpcLog "files finish category=$category exit=$LASTEXITCODE"
        if ($LASTEXITCODE -eq 2) {
            Write-SpcLog "rate limit detected; cooldown ${RateLimitCooldownSeconds}s"
            Start-Sleep -Seconds $RateLimitCooldownSeconds
            break
        }
    }
    if ($Once) {
        break
    }
    Write-SpcLog "file cycle complete sleep=${CycleSleepSeconds}s"
    Start-Sleep -Seconds $CycleSleepSeconds
} while ($true)

Write-SpcLog "SPC file loop stopped"
