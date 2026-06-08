$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$profile = Join-Path $repoRoot ".chrome-spc-ingest-debug"
$url = if ($args.Count -gt 0) { $args[0] } else { "https://www.spc.org.cn/" }

New-Item -ItemType Directory -Force -Path $profile | Out-Null

$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "chrome.exe" -and $_.CommandLine -like "*--remote-debugging-port=9222*" -and $_.CommandLine -like "*$profile*"
}

if (-not $existing) {
    Start-Process -FilePath $chrome -ArgumentList @(
        "--remote-debugging-port=9222",
        "--user-data-dir=$profile",
        "--no-first-run",
        "--new-window",
        $url
    )
}

Start-Sleep -Seconds 2
Invoke-RestMethod "http://127.0.0.1:9222/json/version" | ConvertTo-Json -Depth 4
