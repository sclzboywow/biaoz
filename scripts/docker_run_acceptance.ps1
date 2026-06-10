# Docker compose run acceptance (build, up, log checks, HTTP smoke test).
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File scripts/docker_run_acceptance.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Require-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Error "docker not found in PATH. Install Docker Desktop and retry."
    }
}

function Wait-HttpOk {
    param([string]$Url, [int]$TimeoutSec = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) { return $true }
        } catch { }
        Start-Sleep -Seconds 3
    }
    return $false
}

Require-Docker

Write-Host "== docker compose build =="
docker compose build

Write-Host "== docker compose up postgres =="
docker compose up -d postgres
docker compose ps postgres

Write-Host "== wait postgres healthy =="
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
    $health = docker inspect --format='{{.State.Health.Status}}' (docker compose ps -q postgres) 2>$null
    if ($health -eq "healthy") { break }
    Start-Sleep -Seconds 3
}
if ($health -ne "healthy") { Write-Error "postgres not healthy within timeout" }

Write-Host "== docker compose up api frontend workers =="
docker compose up -d api
docker compose up -d frontend
docker compose up -d collection-worker
docker compose up -d ocr-worker
docker compose ps

Write-Host "== wait API /health =="
if (-not (Wait-HttpOk "http://127.0.0.1:8000/health")) {
    Write-Error "API /health not ready"
}

Write-Host "== alembic current (inside api container) =="
docker compose exec -T api alembic current

Write-Host "== api logs (last 80 lines, alembic/startup) =="
docker compose logs --tail 80 api

Write-Host "== ocr-worker logs (last 40 lines) =="
docker compose logs --tail 40 ocr-worker

Write-Host "== frontend check http://127.0.0.1:5173/ =="
if (-not (Wait-HttpOk "http://127.0.0.1:5173/" 30)) {
    Write-Warning "frontend not responding on 5173"
} else {
    Write-Host "OK frontend HTTP 200"
}

$py = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "== smoke_test_governance.py (HTTP only) =="
& $py (Join-Path $Root "scripts\smoke_test_governance.py") --http-only --api-base http://127.0.0.1:8000
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`n== Docker run acceptance PASSED =="
