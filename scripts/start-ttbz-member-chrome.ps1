param(
    [int]$CdpPort = 9223,
    [int]$SocksPort = 18080,
    [string]$JumpHost = "111.231.22.77",
    [string]$JumpUser = "ubuntu",
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\id_ed25519",
    [string]$Url = "https://www.ttbz.org.cn/standard.html"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$profile = Join-Path $repoRoot ".chrome-ttbz-ingest-debug"
$jumpTunnelScript = Join-Path $repoRoot "scripts\ttbz-jump-tunnel.ps1"
$python = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
$proxyUrl = "socks5://127.0.0.1:$SocksPort"

New-Item -ItemType Directory -Force -Path $profile | Out-Null

function Test-LocalPortListening {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    return $null -ne $conn
}

Write-Output "=== 1/3 jump SOCKS tunnel ($JumpHost -> 127.0.0.1:$SocksPort) ==="
if (Test-Path $jumpTunnelScript) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $jumpTunnelScript -LocalPort $SocksPort -JumpHost $JumpHost -JumpUser $JumpUser -IdentityFile $IdentityFile
} else {
    if (-not (Test-Path $IdentityFile)) { throw "SSH key not found: $IdentityFile" }
    if (-not (Test-LocalPortListening -Port $SocksPort)) {
        Start-Process ssh.exe -ArgumentList @(
            "-i", $IdentityFile, "-N", "-D", "127.0.0.1:$SocksPort",
            "-o", "ExitOnForwardFailure=yes", "-o", "BatchMode=yes",
            "-o", "ServerAliveInterval=30", "-o", "StrictHostKeyChecking=accept-new",
            "$JumpUser@$JumpHost"
        ) -WindowStyle Hidden | Out-Null
        Start-Sleep -Seconds 2
    }
    Write-Output "socks5://127.0.0.1:$SocksPort"
}

if (-not (Test-LocalPortListening -Port $SocksPort)) {
    throw "SOCKS tunnel not ready"
}

$env:TTBZ_HTTP_PROXY = $proxyUrl
Write-Output "TTBZ_HTTP_PROXY=$proxyUrl"

Write-Output "=== 2/3 probe ttbz.org.cn via proxy ==="
if (Test-Path $python) {
    $env:TTBZ_HTTP_PROXY = $proxyUrl
    & $python (Join-Path $repoRoot "scripts\_ttbz_probe_proxy_site.py")
}

Write-Output "=== 3/3 start TTBZ Chrome CDP $CdpPort via SOCKS (not SPC 9222) ==="

$ttbzChrome = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -eq "chrome.exe" -and $_.CommandLine -like "*--remote-debugging-port=$CdpPort*" -and $_.CommandLine -like "*$profile*"
}

foreach ($proc in $ttbzChrome) {
    if ($proc.CommandLine -notlike "*--proxy-server=socks5://127.0.0.1:$SocksPort*") {
        Write-Output "restart Chrome: old instance without SOCKS proxy"
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

$existing = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -eq "chrome.exe" -and $_.CommandLine -like "*--remote-debugging-port=$CdpPort*" -and $_.CommandLine -like "*$profile*"
}

if (-not $existing) {
    Start-Process -FilePath $chrome -ArgumentList @(
        "--remote-debugging-port=$CdpPort",
        "--user-data-dir=$profile",
        "--proxy-server=socks5://127.0.0.1:$SocksPort",
        "--proxy-bypass-list=<-loopback>",
        "--no-first-run",
        "--new-window",
        $Url
    )
}

Start-Sleep -Seconds 3
Write-Output "TTBZ Chrome CDP: http://127.0.0.1:$CdpPort"
Write-Output "Profile: $profile"
Write-Output "Proxy: $proxyUrl via $JumpHost"
Write-Output "Log in to ttbz.org.cn in the Chrome window; ingest will sync cookies via CDP."
Invoke-RestMethod "http://127.0.0.1:$CdpPort/json/version" | ConvertTo-Json -Depth 4

if (Test-Path $python) {
    Write-Output "--- login check ---"
    $env:TTBZ_CDP_URL = "http://127.0.0.1:$CdpPort"
    & $python (Join-Path $repoRoot "scripts\check_ttbz_login.py")
}
