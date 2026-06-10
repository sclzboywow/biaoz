param(
    [switch]$StopChrome
)

$ErrorActionPreference = "Continue"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$logDir = Join-Path $repoRoot "logs"
. (Join-Path $PSScriptRoot "loop-pid-utils.ps1")

function Stop-ByPidFile {
    param(
        [string]$Name,
        [string]$PidPath
    )
    $loopPid = Read-LoopPidFile -Path $PidPath
    if ($loopPid -and (Get-Process -Id $loopPid -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $loopPid -Force -ErrorAction SilentlyContinue
        Write-Output "[$Name] stopped pid=$loopPid"
    } else {
        Write-Output "[$Name] not running"
    }
    if (Test-Path $PidPath) { Remove-Item $PidPath -Force -ErrorAction SilentlyContinue }
}

Stop-ByPidFile -Name "ttbz-file-loop" -PidPath (Join-Path $logDir "ttbz-file-loop.pid")
Stop-ByPidFile -Name "ttbz-jump-tunnel" -PidPath (Join-Path $logDir "ttbz-jump-tunnel.pid")

$sshTunnels = Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match '-D\s+127\.0\.0\.1:18080' }
foreach ($proc in $sshTunnels) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Output "[ttbz-jump-tunnel] stopped stray ssh pid=$($proc.ProcessId)"
}

if ($StopChrome) {
    $profile = Join-Path $repoRoot ".chrome-ttbz-ingest-debug"
    $chromeProcs = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$profile*" }
    foreach ($proc in $chromeProcs) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Output "[ttbz-chrome] stopped pid=$($proc.ProcessId)"
    }
}

$port18080 = Get-NetTCPConnection -LocalPort 18080 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($port18080) {
    Write-Output "[warn] port 18080 still listening owning_pid=$($port18080.OwningProcess)"
} else {
    Write-Output "[ok] port 18080 closed"
}

Write-Output "TTBZ ingest infra stopped (file loop + jump SOCKS tunnel)."
