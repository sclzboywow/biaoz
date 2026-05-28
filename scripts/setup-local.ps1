$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

$python = "C:\Users\MSI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

if (-not (Test-Path (Join-Path $backend ".venv"))) {
  & $python -m venv (Join-Path $backend ".venv")
}

& (Join-Path $backend ".venv\Scripts\python.exe") -m pip install --upgrade pip
& (Join-Path $backend ".venv\Scripts\python.exe") -m pip install -r (Join-Path $backend "requirements.txt")

$envText = "APP_NAME=标准规范与项目依据动态管理系统`nAPI_PREFIX=/api/v1`nDATABASE_URL=postgresql+psycopg://biaoz:biaoz@localhost:5432/biaoz`nSTORAGE_ROOT=./data/standard-docs`nCORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173`n"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText((Join-Path $backend ".env"), $envText, $utf8NoBom)

$nodePath = "C:\Program Files\nodejs"
if (Test-Path $nodePath) {
  $env:Path = "$nodePath;$env:Path"
}

& (Join-Path $nodePath "npm.cmd") install --prefix $frontend

$runtime = Join-Path $root ".runtime"
New-Item -ItemType Directory -Force $runtime | Out-Null

$node22Version = "v22.22.3"
$node22Zip = Join-Path $runtime "node-$node22Version-win-x64.zip"
$node22Dir = Join-Path $runtime "node-$node22Version-win-x64"
if (-not (Test-Path $node22Dir)) {
  if (-not (Test-Path $node22Zip)) {
    Invoke-WebRequest "https://nodejs.org/dist/$node22Version/node-$node22Version-win-x64.zip" -OutFile $node22Zip
  }
  Expand-Archive -LiteralPath $node22Zip -DestinationPath $runtime -Force
}

$n8nDir = Join-Path $runtime "n8n"
New-Item -ItemType Directory -Force $n8nDir | Out-Null
if (-not (Test-Path (Join-Path $n8nDir "package.json"))) {
  Push-Location $n8nDir
  try {
    & (Join-Path $node22Dir "npm.cmd") init -y
    & (Join-Path $node22Dir "npm.cmd") install n8n@1.72.1
  } finally {
    Pop-Location
  }
}

Write-Host "Local setup complete."
