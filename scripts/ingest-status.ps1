$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path $root "backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
  throw "Backend virtualenv missing. Run scripts\setup-local.ps1 first."
}

$code = @'
from pathlib import Path
from sqlalchemy import func
from app.database import SessionLocal
from app.models import Document, DocumentVersion, SystemSetting, UrlSource

db = SessionLocal()
try:
    setting = db.query(SystemSetting).filter(SystemSetting.key == "storage_root").first()
    root = Path(setting.value) if setting else Path("")
    docs = db.query(Document).count()
    versions = db.query(DocumentVersion).count()
    url_sources = db.query(UrlSource).count()
    sources_with_versions = db.query(func.count(func.distinct(DocumentVersion.url_source_id))).scalar()
    duplicate_groups = (
        db.query(DocumentVersion.url_source_id, DocumentVersion.file_hash, func.count(DocumentVersion.id))
        .group_by(DocumentVersion.url_source_id, DocumentVersion.file_hash)
        .having(func.count(DocumentVersion.id) > 1)
        .count()
    )
    missing = 0
    outside = 0
    for (file_path,) in db.query(DocumentVersion.file_path).all():
        raw = Path(file_path)
        full = raw if raw.is_absolute() else root / raw
        if not full.exists():
            missing += 1
        try:
            full.resolve().relative_to(root.resolve())
        except Exception:
            outside += 1
    files = sum(1 for path in root.rglob("*") if path.is_file()) if root.exists() else 0
    size_gb = round(sum(path.stat().st_size for path in root.rglob("*") if path.is_file()) / 1024**3, 2) if root.exists() else 0
    print(f"storage_root={root}")
    print(f"storage_exists={root.exists()}")
    print(f"storage_file_count={files}")
    print(f"storage_size_gb={size_gb}")
    print(f"url_sources={url_sources}")
    print(f"documents={docs}")
    print(f"document_versions={versions}")
    print(f"sources_with_versions={sources_with_versions}")
    print(f"duplicate_url_hash_groups={duplicate_groups}")
    print(f"missing_version_files={missing}")
    print(f"version_files_outside_storage_root={outside}")
finally:
    db.close()
'@

Push-Location $backend
try {
  $code | & $python -
} finally {
  Pop-Location
}
