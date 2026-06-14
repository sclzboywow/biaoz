$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("cleanup-duplicate-versions-batch-{0:yyyyMMdd-HHmmss}.log" -f (Get-Date))
$psql = "C:\Program Files\PostgreSQL\17\bin\psql.exe"
if (-not (Test-Path $psql)) { throw "psql not found: $psql" }

$env:PGPASSWORD = "biaoz"
Write-Host "batch cleanup -> $logFile"

function Invoke-Psql([string]$Sql) {
    & $psql -h localhost -U biaoz -d biaoz -v ON_ERROR_STOP=1 -c $Sql 2>&1 | ForEach-Object { Write-Host $_; Add-Content -Path $logFile -Value $_ }
    if ($LASTEXITCODE -ne 0) { throw "psql failed" }
}

Invoke-Psql "SET statement_timeout = 0;"
Invoke-Psql @"
SELECT count(*) AS duplicate_rows_to_remove
FROM document_versions dv
WHERE EXISTS (
    SELECT 1 FROM document_versions earlier
    WHERE earlier.document_id = dv.document_id
      AND lower(earlier.file_hash) = lower(dv.file_hash)
      AND earlier.id < dv.id
);
"@

$batch = 0
while ($true) {
    $batch++
    $out = & $psql -h localhost -U biaoz -d biaoz -v ON_ERROR_STOP=1 -Atc @"
WITH doomed AS (
    SELECT dv.id
    FROM document_versions dv
    WHERE EXISTS (
        SELECT 1 FROM document_versions earlier
        WHERE earlier.document_id = dv.document_id
          AND lower(earlier.file_hash) = lower(dv.file_hash)
          AND earlier.id < dv.id
    )
    ORDER BY dv.id
    LIMIT 500
)
DELETE FROM document_versions dv
USING doomed d
WHERE dv.id = d.id;
"@ 2>&1
    $deleted = [int]($out | Select-Object -Last 1)
    Write-Host "batch=$batch deleted=$deleted"
    Add-Content -Path $logFile -Value "batch=$batch deleted=$deleted"
    if ($deleted -eq 0) { break }
}

Invoke-Psql @"
WITH affected AS (
    SELECT DISTINCT document_id
    FROM document_versions
)
UPDATE document_versions dv
SET is_current = (dv.id = latest.version_id)
FROM (
    SELECT document_id, max(id) AS version_id
    FROM document_versions
    GROUP BY document_id
) latest
WHERE dv.document_id = latest.document_id;
"@

Invoke-Psql @"
UPDATE documents d
SET current_version_id = latest.version_id
FROM (
    SELECT document_id, max(id) AS version_id
    FROM document_versions
    GROUP BY document_id
) latest
WHERE d.id = latest.document_id;
"@

Invoke-Psql @"
SELECT count(*) AS remaining_duplicate_rows
FROM document_versions dv
WHERE EXISTS (
    SELECT 1 FROM document_versions earlier
    WHERE earlier.document_id = dv.document_id
      AND lower(earlier.file_hash) = lower(dv.file_hash)
      AND earlier.id < dv.id
);
"@

Write-Host "done. log=$logFile"
