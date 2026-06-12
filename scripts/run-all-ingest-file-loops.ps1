param(
    [switch]$Once,
    [switch]$SkipSacinfoPortal,
    [switch]$IncludeTtbz,
    [ValidateSet("cn-only", "cn-jj", "all")]
    [string]$SpcFocusMode = "cn-only",
    [int]$BaiduPanWorkers = 6,
    [int]$MaxLoopLogMB = 100
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
. (Join-Path $PSScriptRoot "loop-pid-utils.ps1")

function Rotate-LoopLogIfLarge {
    param([string]$Path, [int]$MaxMB)
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $item = Get-Item -LiteralPath $Path
    if ($item.Length -lt ($MaxMB * 1MB)) {
        return
    }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $archivePath = "$Path.$stamp"
    Move-Item -LiteralPath $Path -Destination $archivePath -Force
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

    Rotate-LoopLogIfLarge -Path $outLog -MaxMB $MaxLoopLogMB
    Rotate-LoopLogIfLarge -Path $errLog -MaxMB $MaxLoopLogMB

    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $ScriptPath) + $ScriptArgs
    $procInfo = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru -WindowStyle Hidden
    Write-LoopPidFile -Path $pidFile -ProcessId $procInfo.Id
    Write-Output "[$Name] started pid=$($procInfo.Id) log=$outLog"
}

$onceArg = @()
if ($Once) { $onceArg = @("-Once") }

Start-BackgroundLoop -Name "openstd-file-loop" -ScriptPath (Join-Path $repoRoot "scripts\run-openstd-file-loop.ps1") -ScriptArgs $onceArg
if ($SkipSacinfoPortal) {
    Write-Output "[sacinfo-portal-industry-file-loop] skipped (SkipSacinfoPortal)"
    Write-Output "[sacinfo-portal-local-file-loop] skipped (SkipSacinfoPortal)"
} else {
    Start-BackgroundLoop -Name "sacinfo-portal-industry-file-loop" -ScriptPath (Join-Path $repoRoot "scripts\run-sacinfo-industry-file-loop.ps1") -ScriptArgs $onceArg
    Start-BackgroundLoop -Name "sacinfo-portal-local-file-loop" -ScriptPath (Join-Path $repoRoot "scripts\run-sacinfo-local-file-loop.ps1") -ScriptArgs $onceArg
}
if ($IncludeTtbz) {
    Start-BackgroundLoop -Name "ttbz-file-loop" -ScriptPath (Join-Path $repoRoot "scripts\run-ttbz-file-loop.ps1") -ScriptArgs $onceArg
} else {
    $ttbzPidFile = Join-Path $logDir "ttbz-file-loop.pid"
    $ttbzPid = Read-LoopPidFile -Path $ttbzPidFile
    if ($ttbzPid -and (Get-Process -Id $ttbzPid -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $ttbzPid -Force -ErrorAction SilentlyContinue
        if (Test-Path $ttbzPidFile) { Remove-Item $ttbzPidFile -Force }
        Write-Output "[ttbz-file-loop] stopped pid=$ttbzPid (TTBZ ingest paused)"
    } else {
        Write-Output "[ttbz-file-loop] skipped (TTBZ ingest paused; use -IncludeTtbz to enable)"
    }
}
Start-BackgroundLoop -Name "qybz-file-loop" -ScriptPath (Join-Path $repoRoot "scripts\run-qybz-file-loop.ps1") -ScriptArgs $onceArg
$spcArgs = @("-FocusMode", $SpcFocusMode) + $onceArg
Start-BackgroundLoop -Name "spc-file-loop" -ScriptPath (Join-Path $repoRoot "scripts\run-spc-file-loop.ps1") -ScriptArgs $spcArgs

Start-BackgroundLoop -Name "baidu-pan-sync-loop" -ScriptPath (Join-Path $repoRoot "scripts\run-baidu-pan-sync-loop.ps1") -ScriptArgs @("-Limit", "500", "-Workers", "$BaiduPanWorkers")

$monitorScript = Join-Path $repoRoot "scripts\run-ingest-monitor.ps1"
$monitorPidFile = Join-Path $logDir "ingest-monitor.pid"
$monitorPid = Read-LoopPidFile -Path $monitorPidFile
if ($null -eq $monitorPid -or -not (Get-Process -Id $monitorPid -ErrorAction SilentlyContinue)) {
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $monitorScript -Background -IntervalMinutes 30 | Out-Null
    Write-Output "[ingest-monitor] started interval=30m"
} else {
    Write-Output "[ingest-monitor] already running pid=$monitorPid"
}

Write-Output "File ingest loops launched (openstd/sacinfo/spc/qybz/baidu-sync; ttbz=$(if ($IncludeTtbz) { 'on' } else { 'off' }))."
