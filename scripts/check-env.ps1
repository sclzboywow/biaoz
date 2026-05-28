$ErrorActionPreference = "Continue"

Write-Host "Checking local runtime environment..." -ForegroundColor Cyan

function Test-Command($Name) {
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if ($cmd) {
    if ($Name -eq "python" -and $cmd.Source -like "*WindowsApps*") {
      Write-Host "[WARN] $Name points to Windows Store alias -> $($cmd.Source)" -ForegroundColor Yellow
    } else {
      Write-Host "[OK] $Name -> $($cmd.Source)" -ForegroundColor Green
    }
  } else {
    Write-Host "[MISS] $Name not found" -ForegroundColor Yellow
  }
}

Test-Command "docker"
Test-Command "python"
Test-Command "node"
Test-Command "npm"
Test-Command "git"

if (Test-Path ".env") {
  Write-Host "[OK] .env exists" -ForegroundColor Green
} else {
  Write-Host "[MISS] .env not found. Run: Copy-Item .env.example .env" -ForegroundColor Yellow
}
