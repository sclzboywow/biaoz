param(
    [switch]$Once,
    [int]$TrustedPages = 50,
    [int]$TrustedWorkers = 2,
    [int]$SpcPages = 500,
    [int]$SpcWorkers = 6
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

Start-BackgroundLoop `
    -Name "trusted-sources-loop" `
    -ScriptPath (Join-Path $repoRoot "scripts\run-trusted-sources-loop.ps1") `
    -ScriptArgs (@("-Pages", "$TrustedPages", "-Workers", "$TrustedWorkers", "-OnlyPendingCategories") + $onceArg)

Start-BackgroundLoop `
    -Name "spc-metadata-slices-loop" `
    -ScriptPath (Join-Path $repoRoot "scripts\run-spc-metadata-slices-loop.ps1") `
    -ScriptArgs (@("-Pages", "$SpcPages", "-Workers", "$SpcWorkers") + $onceArg)

Start-BackgroundLoop `
    -Name "governance-loop" `
    -ScriptPath (Join-Path $repoRoot "scripts\run-governance-loop.ps1") `
    -ScriptArgs (@("-ProfileLimit", "5000", "-DecisionLimit", "5000", "-OcrTaskLimit", "500", "-AlertSweepLimit", "3000", "-CycleSleepSeconds", "900") + $onceArg)

Start-BackgroundLoop `
    -Name "ocr-worker" `
    -ScriptPath (Join-Path $repoRoot "scripts\run-ocr-worker-loop.ps1") `
    -ScriptArgs $onceArg

$guojiScript = Join-Path $repoRoot "scripts\run-guojiabiaozhun-sync.ps1"
$guojiPidFile = Join-Path $logDir "guojiabiaozhun-sync.pid"
$guojiLauncherPid = Ensure-LoopPidFile -PidPath (Join-Path $logDir "guojiabiaozhun-sync-launcher.pid") -ScriptPath $guojiScript
if ($null -ne $guojiLauncherPid -and (Get-Process -Id $guojiLauncherPid -ErrorAction SilentlyContinue)) {
    Write-Output "[guojiabiaozhun-sync] launcher already running pid=$guojiLauncherPid"
} else {
    $guojiArgs = @("-Background", "-IntervalSeconds", "30", "-RequestDelaySeconds", "1", "-PageSize", "200", "-CooldownSeconds", "1800")
    if ($Once) { $guojiArgs += "-Once" }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $guojiScript @guojiArgs | ForEach-Object { Write-Output "[guojiabiaozhun-sync] $_" }
}

Write-Output "Metadata ingest loops launched (trusted-sources/spc-slices/governance/ocr-worker/guojiabiaozhun)."
