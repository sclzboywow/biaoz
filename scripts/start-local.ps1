$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$logs = Join-Path $root "logs"

New-Item -ItemType Directory -Force $logs | Out-Null

$nodePath = "C:\Program Files\nodejs"
if (Test-Path $nodePath) {
  $env:Path = "$nodePath;$env:Path"
}

$apiOut = Join-Path $logs "api.out.log"
$apiErr = Join-Path $logs "api.err.log"
$frontOut = Join-Path $logs "frontend.out.log"
$frontErr = Join-Path $logs "frontend.err.log"
$n8nOut = Join-Path $logs "n8n.out.log"
$n8nErr = Join-Path $logs "n8n.err.log"

$apiPython = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $apiPython)) {
  throw "Backend virtualenv missing. Run setup first."
}

& $apiPython -m alembic upgrade head

$api = Start-Process -FilePath $apiPython `
  -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
  -WorkingDirectory $backend `
  -RedirectStandardOutput $apiOut `
  -RedirectStandardError $apiErr `
  -WindowStyle Hidden `
  -PassThru

$npm = Join-Path $nodePath "npm.cmd"
if (-not (Test-Path $npm)) {
  throw "npm.cmd missing. Install Node.js LTS first."
}

$frontendProcess = Start-Process -FilePath $npm `
  -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "5173") `
  -WorkingDirectory $frontend `
  -RedirectStandardOutput $frontOut `
  -RedirectStandardError $frontErr `
  -WindowStyle Hidden `
  -PassThru

$node22Dir = Join-Path $root ".runtime\node-v22.22.3-win-x64"
$n8nDir = Join-Path $root ".runtime\n8n"
if ((Test-Path $node22Dir) -and (Test-Path $n8nDir)) {
  $env:Path = "$node22Dir;$env:Path"
  $n8nUser = Join-Path $root ".runtime\n8n-user"
  New-Item -ItemType Directory -Force $n8nUser | Out-Null
  $env:N8N_PORT = "5678"
  $env:N8N_HOST = "127.0.0.1"
  $env:N8N_PROTOCOL = "http"
  $env:N8N_USER_FOLDER = $n8nUser
  $env:N8N_DIAGNOSTICS_ENABLED = "false"
  $env:N8N_VERSION_NOTIFICATIONS_ENABLED = "false"
  $env:N8N_SECURE_COOKIE = "false"
  $n8n = Start-Process -FilePath (Join-Path $node22Dir "npx.cmd") `
    -ArgumentList @("n8n", "start") `
    -WorkingDirectory $n8nDir `
    -RedirectStandardOutput $n8nOut `
    -RedirectStandardError $n8nErr `
    -WindowStyle Hidden `
    -PassThru
  Write-Host "n8n PID: $($n8n.Id)"
} else {
  Write-Host "n8n runtime not found. Existing API and frontend were started."
}

Write-Host "API PID: $($api.Id)"
Write-Host "Frontend PID: $($frontendProcess.Id)"
Write-Host "API: http://127.0.0.1:8000"
Write-Host "Frontend: http://127.0.0.1:5173"
Write-Host "n8n: http://127.0.0.1:5678"
