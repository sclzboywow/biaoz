param(
    [string]$JumpHost = "111.231.22.77",
    [string]$JumpUser = "ubuntu",
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\id_ed25519",
    [int]$LocalPort = 18080
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$pidFile = Join-Path $logDir "ttbz-jump-tunnel.pid"
. (Join-Path $PSScriptRoot "loop-pid-utils.ps1")

function Test-LocalPortListening {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    return $null -ne $conn
}

function Stop-StaleTunnel {
    param([int]$ProcessId)
    if (-not $ProcessId) { return }
    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($proc -and $proc.ProcessName -match '^(ssh)$') {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

$existingPid = Read-LoopPidFile -Path $pidFile
if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue) -and (Test-LocalPortListening -Port $LocalPort)) {
    Write-Output "ttbz jump tunnel already running pid=$existingPid port=$LocalPort"
    Write-Output "socks5://127.0.0.1:$LocalPort"
    exit 0
}

Stop-StaleTunnel -ProcessId $existingPid
if (Test-Path $pidFile) { Remove-Item $pidFile -Force }

if (-not (Test-Path $IdentityFile)) {
    throw "SSH key not found: $IdentityFile"
}

$sshArgs = @(
    "-i", $IdentityFile,
    "-N",
    "-D", "127.0.0.1:$LocalPort",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    "$JumpUser@$JumpHost"
)

$proc = Start-Process -FilePath "ssh.exe" -ArgumentList $sshArgs -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 2

if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) {
    throw "SSH SOCKS tunnel failed to start"
}
if (-not (Test-LocalPortListening -Port $LocalPort)) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    throw "SOCKS port $LocalPort is not listening after tunnel start"
}

Write-LoopPidFile -Path $pidFile -ProcessId $proc.Id
Write-Output "ttbz jump tunnel started pid=$($proc.Id) port=$LocalPort via $JumpHost"
Write-Output "socks5://127.0.0.1:$LocalPort"
