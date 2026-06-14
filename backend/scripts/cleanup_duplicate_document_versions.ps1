$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("cleanup-duplicate-versions-{0:yyyyMMdd-HHmmss}.log" -f (Get-Date))
$psql = "C:\Program Files\PostgreSQL\17\bin\psql.exe"
if (-not (Test-Path $psql)) { throw "psql not found: $psql" }

$sql = @'
SET statement_timeout = 0;

CREATE TEMP TABLE tmp_duplicate_versions AS
WITH ranked AS (
    SELECT
        id,
        document_id,
        file_hash,
        file_path,
        change_type,
        ROW_NUMBER() OVER (
            PARTITION BY document_id, lower(file_hash)
            ORDER BY id
        ) AS rn,
        FIRST_VALUE(id) OVER (
            PARTITION BY document_id, lower(file_hash)
            ORDER BY id
        ) AS keep_id
    FROM document_versions
    WHERE file_hash IS NOT NULL AND btrim(file_hash) <> ''
)
SELECT id AS delete_id, keep_id, document_id, file_path, change_type
FROM ranked
WHERE rn > 1;

SELECT 'to_delete' AS step, count(*)::text AS value FROM tmp_duplicate_versions;

UPDATE standard_file_matches t
SET document_version_id = d.keep_id
FROM tmp_duplicate_versions d
WHERE t.document_version_id = d.delete_id;

UPDATE standard_change_logs t
SET document_version_id = d.keep_id
FROM tmp_duplicate_versions d
WHERE t.document_version_id = d.delete_id;

UPDATE local_file_intake_tasks t
SET linked_version_id = d.keep_id
FROM tmp_duplicate_versions d
WHERE t.linked_version_id = d.delete_id;

DELETE FROM document_versions dv
USING tmp_duplicate_versions d
WHERE dv.id = d.delete_id;

WITH latest AS (
    SELECT d.document_id, max(dv.id) AS version_id
    FROM tmp_duplicate_versions d
    JOIN document_versions dv ON dv.document_id = d.document_id
    GROUP BY d.document_id
)
UPDATE document_versions dv
SET is_current = (dv.id = latest.version_id)
FROM latest
WHERE dv.document_id = latest.document_id;

WITH latest AS (
    SELECT d.document_id, max(dv.id) AS version_id
    FROM tmp_duplicate_versions d
    JOIN document_versions dv ON dv.document_id = d.document_id
    GROUP BY d.document_id
)
UPDATE documents doc
SET current_version_id = latest.version_id
FROM latest
WHERE doc.id = latest.document_id;

SELECT 'remaining_duplicate_groups' AS step, count(*)::text AS value
FROM (
    SELECT document_id, lower(file_hash) AS h
    FROM document_versions
    WHERE file_hash IS NOT NULL AND btrim(file_hash) <> ''
    GROUP BY 1, 2
    HAVING count(*) > 1
) x;

SELECT 'document_versions_total' AS step, count(*)::text AS value FROM document_versions;
'@

Write-Host "running cleanup -> $logFile"
$sqlFile = Join-Path $logDir ("cleanup-duplicate-versions-{0:yyyyMMdd-HHmmss}.sql" -f (Get-Date))
Set-Content -Path $sqlFile -Value $sql -Encoding UTF8
$env:PGPASSWORD = "biaoz"
& $psql -h localhost -U biaoz -d biaoz -v ON_ERROR_STOP=1 -f $sqlFile 2>&1 | Tee-Object -FilePath $logFile | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) { throw "psql cleanup failed, see $logFile" }
Write-Host "done. log=$logFile sql=$sqlFile"
