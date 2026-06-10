# Local stack acceptance when Docker Hub is unavailable or compose cannot bind 5432.
# Mirrors docker-compose services using local venv + existing PostgreSQL.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/local_run_acceptance.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Py = Join-Path $Backend ".venv\Scripts\python.exe"
$Logs = Join-Path $Root "logs\acceptance"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null

function Wait-HttpOk {
    param([string]$Url, [int]$TimeoutSec = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) { return $true }
        } catch { }
        Start-Sleep -Seconds 2
    }
    return $false
}

Set-Location $Backend
Write-Host "== alembic upgrade head =="
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $Py -m alembic upgrade head 2>&1 | Tee-Object -FilePath (Join-Path $Logs "alembic.log")
& $Py -m alembic current 2>&1 | Tee-Object -FilePath (Join-Path $Logs "alembic-current.log") -Append
$ErrorActionPreference = $prevEap

Write-Host "== start API =="
$api = Start-Process -FilePath $Py -ArgumentList @("-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8000") -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Logs "api.log") -RedirectStandardError (Join-Path $Logs "api.err.log")
Start-Sleep -Seconds 3
if (-not (Wait-HttpOk "http://127.0.0.1:8000/health" 60)) { throw "API failed to start" }

Write-Host "== build frontend =="
Set-Location $Frontend
npm run build 2>&1 | Tee-Object -FilePath (Join-Path $Logs "frontend-build.log")
Write-Host "== serve frontend on 5173 =="
$fe = Start-Process -FilePath $Py -ArgumentList @("-m","http.server","5173","--directory","dist") -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Logs "frontend.log") -RedirectStandardError (Join-Path $Logs "frontend.err.log")
Start-Sleep -Seconds 2
if (-not (Wait-HttpOk "http://127.0.0.1:5173/" 30)) { throw "frontend failed to start" }

Set-Location $Backend
Write-Host "== start collection-worker =="
$col = Start-Process -FilePath $Py -ArgumentList @("-m","app.collection_worker","--poll-seconds","10") -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Logs "collection-worker.log") -RedirectStandardError (Join-Path $Logs "collection-worker.err.log")

Write-Host "== start ocr-worker =="
$ocr = Start-Process -FilePath $Py -ArgumentList @("-m","app.ocr_download_worker","--poll-seconds","10") -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Logs "ocr-worker.log") -RedirectStandardError (Join-Path $Logs "ocr-worker.err.log")
Start-Sleep -Seconds 5

Write-Host "== ocr-worker log tail =="
Get-Content (Join-Path $Logs "ocr-worker.log") -ErrorAction SilentlyContinue | Select-Object -Last 10
Get-Content (Join-Path $Logs "ocr-worker.err.log") -ErrorAction SilentlyContinue | Select-Object -Last 10

Write-Host "== smoke_test_governance.py =="
& $Py (Join-Path $Root "scripts\smoke_test_governance.py") --api-base http://127.0.0.1:8000
$code = $LASTEXITCODE

Write-Host "== acceptance PIDs api=$($api.Id) frontend=$($fe.Id) collection=$($col.Id) ocr=$($ocr.Id) =="
Write-Host "Logs: $Logs"
if ($code -ne 0) { exit $code }
Write-Host "`n== Local run acceptance PASSED =="
