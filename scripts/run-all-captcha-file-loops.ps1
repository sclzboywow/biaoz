param(
    [switch]$Once
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
. (Join-Path $PSScriptRoot "loop-pid-utils.ps1")

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

    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $ScriptPath) + $ScriptArgs
    $procInfo = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru -WindowStyle Hidden
    Write-LoopPidFile -Path $pidFile -ProcessId $procInfo.Id
    Write-Output "[$Name] started pid=$($procInfo.Id) log=$outLog"
}

$onceArg = @()
if ($Once) { $onceArg = @("-Once") }

Start-BackgroundLoop -Name "openstd-file-loop" -ScriptPath (Join-Path $repoRoot "scripts\run-openstd-file-loop.ps1") -ScriptArgs $onceArg
Start-BackgroundLoop -Name "sacinfo-portal-industry-file-loop" -ScriptPath (Join-Path $repoRoot "scripts\run-sacinfo-industry-file-loop.ps1") -ScriptArgs $onceArg
Start-BackgroundLoop -Name "sacinfo-portal-local-file-loop" -ScriptPath (Join-Path $repoRoot "scripts\run-sacinfo-local-file-loop.ps1") -ScriptArgs $onceArg

Write-Output "All captcha ingest loops launched. storage_backend should be dual for local + Baidu Pan."
