param(
    [string[]]$Categories = @("CN"),
    [ValidateSet("cn-only", "cn-jj", "all")]
    [string]$FocusMode = "cn-only",
    [int]$FileLimit = 100,
    [double]$FileDelay = 2.0,
    [int]$FileTimeoutSeconds = 240,
    [int]$CycleSleepSeconds = 30,
    [int]$RateLimitCooldownSeconds = 1800,
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
$pidFile = Join-Path $logDir "spc-file-loop.pid"
. (Join-Path $PSScriptRoot "loop-pid-utils.ps1")
Write-LoopPidFile -Path $pidFile -ProcessId $PID

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

function Reset-SpcCursor {
    param([string]$Category)
    $path = Get-SpcCursorPath -Category $Category
    if (Test-Path $path) {
        Remove-Item $path -Force
    }
}

function Update-SpcCursorFromOutput {
    param([string]$Category, [string[]]$OutputLines)
    $candidateCount = $null
    foreach ($line in $OutputLines) {
        if ($line -match '^spc_batch_candidates (\[.*\])$') {
            try {
                $candidateCount = (@((ConvertFrom-Json $Matches[1]))).Count
            } catch {
                $candidateCount = $null
            }
            continue
        }
        if ($line -notmatch '^spc_batch_summary ') {
            continue
        }
        $payload = $line.Substring('spc_batch_summary '.Length) | ConvertFrom-Json
        if ($null -ne $payload.last_resource_id) {
            Set-SpcCursor -Category $Category -ResourceId ([int]$payload.last_resource_id)
        }
        break
    }
    return $candidateCount
}

function Write-SpcLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] $Message"
}

function Get-RankedCategories {
    $priority = @("CN", "JJ")
    $rankScript = Join-Path $repoRoot "scripts\spc_ingest_scheduler.py"
    $raw = & $python $rankScript 2>$null
    $rest = @("QT", "DFBZ", "TC", "QYBZ")
    if ($raw) {
        $rest = @($raw.Trim().Split(",") | Where-Object { $_ -and ($_ -notin $priority) })
    }
    return @($priority + $rest)
}

function Get-CategoryLimit {
    param([string]$Category)
    if ($Category -eq "CN") {
        return [Math]::Max($FileLimit * 3, 200)
    }
    if ($Category -in @("CN", "JJ")) {
        return [Math]::Max($FileLimit * 2, 150)
    }
    $rankScript = Join-Path $repoRoot "scripts\spc_ingest_scheduler.py"
    $value = & $python $rankScript --suggest-limit $Category --base-limit $FileLimit 2>$null
    if ($value -match '^\d+$') {
        return [int]$value
    }
    return $FileLimit
}

function Resolve-SpcCategories {
    if ($Categories.Count -gt 0) {
        return $Categories
    }
    switch ($FocusMode) {
        "cn-only" { return @("CN") }
        "cn-jj" { return @("CN", "JJ") }
        default { return Get-RankedCategories }
    }
}

$Categories = Resolve-SpcCategories

Write-SpcLog "SPC file loop starting focus=$FocusMode categories=$($Categories -join ',') file_limit=$FileLimit file_timeout_seconds=$FileTimeoutSeconds"

try {
    & (Join-Path $repoRoot "scripts\start-spc-member-chrome.ps1") | Out-Null
    Write-SpcLog "member Chrome debug port ready"
} catch {
    Write-SpcLog "member Chrome startup/check failed: $($_.Exception.Message)"
}

try {
do {
    foreach ($category in $Categories) {
        $cursor = Get-SpcCursor -Category $category
        $cursorArg = @()
        if ($null -ne $cursor) {
            $cursorArg = @("--start-after-resource-id", [string]$cursor)
            Write-SpcLog "files start category=$category limit=$(Get-CategoryLimit $category) cursor=$cursor"
        } else {
            Write-SpcLog "files start category=$category limit=$(Get-CategoryLimit $category) cursor=(none)"
        }
        $categoryLimit = Get-CategoryLimit $category
        $output = & $python (Join-Path $repoRoot "scripts\batch_ingest_spc_online_files.py") `
            --category $category `
            --limit $categoryLimit `
            --delay $FileDelay `
            --timeout $FileTimeoutSeconds `
            --max-consecutive-errors $MaxConsecutiveErrors `
            --cooldown-on-rate-limit 0 `
            --defer-baidu-upload `
            @cursorArg 2>&1
        $output | ForEach-Object { Write-Output $_ }
        $candidateCount = Update-SpcCursorFromOutput -Category $category -OutputLines $output
        if ($candidateCount -eq 0) {
            Reset-SpcCursor -Category $category
            Write-SpcLog "no pending candidates for category=$category; cursor reset to scan from beginning"
        }
        Write-SpcLog "files finish category=$category exit=$LASTEXITCODE candidates=$candidateCount"
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
    if ($FocusMode -eq "all") {
        $Categories = Get-RankedCategories
    }
} while ($true)
} finally {
    Remove-LoopPidFileIfOwned -Path $pidFile -ProcessId $PID
}

Write-SpcLog "SPC file loop stopped"
