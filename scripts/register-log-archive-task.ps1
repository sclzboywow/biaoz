param(
  [string]$TaskName = "BiaozOperationalLogArchive",
  [int]$RetentionDays = 90,
  [string]$At = "03:30"
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
$script = Join-Path $root "scripts\archive_operational_logs.py"

if (-not (Test-Path $python)) {
  throw "Backend virtualenv missing: $python"
}

if (-not (Test-Path $script)) {
  throw "Archive script missing: $script"
}

$action = New-ScheduledTaskAction `
  -Execute $python `
  -Argument "`"$script`" --retention-days $RetentionDays" `
  -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Monthly -DaysOfMonth 1 -At $At
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description "Archive low-value operational logs for biaoz while keeping failure, status, change, and evidence history." `
  -Force | Out-Null

Write-Host "Registered $TaskName to run monthly on day 1 at $At."
