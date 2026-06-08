param(
    [switch]$Once
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Start-BackgroundLoop {
    param(
        [string]$Name,
        [string]$ScriptPath,
        [string[]]$ScriptArgs = @()
    )

    $outLog = Join-Path $logDir "$Name.out.log"
    $errLog = Join-Path $logDir "$Name.err.log"
    $pidFile = Join-Path $logDir "$Name.pid"

    if (Test-Path $pidFile) {
        $oldPid = (Get-Content -Path $pidFile -Raw).Trim()
        if ($oldPid -match '^\d+$') {
            $proc = Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Output "[$Name] already running pid=$oldPid"
                return
            }
        }
    }

    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $ScriptPath) + $ScriptArgs
    $procInfo = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru -WindowStyle Hidden
    Set-Content -Path $pidFile -Value $procInfo.Id -Encoding utf8
    Write-Output "[$Name] started pid=$($procInfo.Id) log=$outLog"
}

$onceArg = @()
if ($Once) { $onceArg = @("-Once") }

Start-BackgroundLoop -Name "openstd-file-loop" -ScriptPath (Join-Path $repoRoot "scripts\run-openstd-file-loop.ps1") -ScriptArgs $onceArg
Start-BackgroundLoop -Name "sacinfo-portal-file-loop" -ScriptPath (Join-Path $repoRoot "scripts\run-sacinfo-portal-file-loop.ps1") -ScriptArgs $onceArg

Write-Output "All captcha ingest loops launched. storage_backend should be dual for local + Baidu Pan."
