param(
    [ValidateSet("industry", "local", "all")]
    [string]$Platform = "all",
    [int]$FileLimit = 1000,
    [double]$FileDelay = 3.0,
    [int]$FileTimeoutSeconds = 60,
    [int]$CycleSleepSeconds = 30,
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
$loopSlug = switch ($Platform) {
    "industry" { "sacinfo-portal-industry-file-loop" }
    "local" { "sacinfo-portal-local-file-loop" }
    default { "sacinfo-portal-file-loop" }
}
$pidFile = Join-Path $logDir "$loopSlug.pid"
. (Join-Path $PSScriptRoot "loop-pid-utils.ps1")
Write-LoopPidFile -Path $pidFile -ProcessId $PID

function Get-SacinfoCursorPath {
    param([string]$Name)
    return Join-Path $logDir "sacinfo-portal-loop-$Name.cursor"
}

function Get-SacinfoCursor {
    param([string]$Name)
    $path = Get-SacinfoCursorPath -Name $Name
    if (-not (Test-Path $path)) { return $null }
    $value = (Get-Content -Path $path -Raw).Trim()
    if ($value -match '^\d+$') { return [int]$value }
    return $null
}

function Set-SacinfoCursor {
    param([string]$Name, [int]$ResourceId)
    Set-Content -Path (Get-SacinfoCursorPath -Name $Name) -Value $ResourceId -Encoding utf8
}

function Update-SacinfoCursorFromOutput {
    param([string]$Name, [string[]]$OutputLines)
    foreach ($line in $OutputLines) {
        if ($line -notmatch '^sacinfo_batch_summary ') { continue }
        $payload = $line.Substring('sacinfo_batch_summary '.Length) | ConvertFrom-Json
        if ($null -ne $payload.last_resource_id) {
            Set-SacinfoCursor -Name $Name -ResourceId ([int]$payload.last_resource_id)
        }
        break
    }
}

function Write-SacinfoLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Output "[$timestamp] $Message"
}

$platforms = @()
if ($Platform -eq "all") {
    $platforms = @("industry", "local")
} else {
    $platforms = @($Platform)
}

Write-SacinfoLog "sacinfo portal captcha file loop starting platforms=$($platforms -join ',') file_limit=$FileLimit"

try {
do {
    foreach ($platform in $platforms) {
        $cursor = Get-SacinfoCursor -Name $platform
        $cursorArg = @()
        if ($null -ne $cursor) {
            $cursorArg = @("--start-after-resource-id", [string]$cursor)
            Write-SacinfoLog "files start platform=$platform limit=$FileLimit cursor=$cursor"
        } else {
            Write-SacinfoLog "files start platform=$platform limit=$FileLimit cursor=(none)"
        }

        $env:SACINFO_CAPTCHA_MAX_ATTEMPTS = [string]$MaxAttempts
        $output = & $python (Join-Path $repoRoot "scripts\batch_ingest_sacinfo_portal_files.py") `
            --platform $platform `
            --limit $FileLimit `
            --delay $FileDelay `
            --timeout $FileTimeoutSeconds `
            --max-attempts $MaxAttempts `
            --defer-baidu-upload `
            @cursorArg 2>&1
        $output | ForEach-Object { Write-Output $_ }
        Update-SacinfoCursorFromOutput -Name $platform -OutputLines $output
        Write-SacinfoLog "files finish platform=$platform exit=$LASTEXITCODE"
    }

    if ($Once) { break }
    Write-SacinfoLog "cycle complete sleep=${CycleSleepSeconds}s"
    Start-Sleep -Seconds $CycleSleepSeconds
} while ($true)
} finally {
    Remove-LoopPidFileIfOwned -Path $pidFile -ProcessId $PID
}

Write-SacinfoLog "sacinfo portal captcha file loop stopped"
