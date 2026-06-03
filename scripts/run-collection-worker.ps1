param(
  [switch]$Once,
  [int]$MaxTasks = 0,
  [double]$PollSeconds = 5,
  [string]$WorkerId = ""
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path $root "backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
  throw "Backend virtualenv missing. Run scripts\setup-local.ps1 first."
}

$args = @("-m", "app.collection_worker", "--poll-seconds", "$PollSeconds")
if ($Once) {
  $args += "--once"
} elseif ($MaxTasks -gt 0) {
  $args += @("--max-tasks", "$MaxTasks")
}
if ($WorkerId) {
  $args += @("--worker-id", "$WorkerId")
}

Push-Location $backend
try {
  & $python $args
} finally {
  Pop-Location
}
