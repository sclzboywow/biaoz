from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import func

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.guobiao_sync import MONITORED_CHANGE_FIELDS  # noqa: E402
from app.storage import check_storage_root  # noqa: E402
from app.config import get_settings  # noqa: E402


def safe_delete_file(storage_root: Path, relative_path: str | None) -> bool:
    if not relative_path:
        return False
    path = Path(relative_path)
    if not path.is_absolute():
        path = storage_root / path
    try:
        resolved = path.resolve()
        root = storage_root.resolve()
        if not str(resolved).lower().startswith(str(root).lower()):
            return False
        if resolved.exists() and resolved.is_file():
            resolved.unlink()
            return True
    except OSError:
        return False
    return False


def main() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        storage = check_storage_root(db, settings.storage_root)
        if not storage.available:
            raise SystemExit(f"storage unavailable: {storage.message}")

        duplicate_versions_deleted = 0
        duplicate_documents_deleted = 0
        duplicate_files_deleted = 0
        groups = (
            db.query(models.DocumentVersion.url_source_id, models.DocumentVersion.file_hash, func.count(models.DocumentVersion.id))
            .filter(models.DocumentVersion.url_source_id.is_not(None))
            .group_by(models.DocumentVersion.url_source_id, models.DocumentVersion.file_hash)
            .having(func.count(models.DocumentVersion.id) > 1)
            .all()
        )
        for source_id, file_hash, _count in groups:
            versions = (
                db.query(models.DocumentVersion)
                .filter(
                    models.DocumentVersion.url_source_id == source_id,
                    models.DocumentVersion.file_hash == file_hash,
                )
                .order_by(models.DocumentVersion.id)
                .all()
            )
            keep = versions[0]
            keep.is_current = True
            for version in versions[1:]:
                if safe_delete_file(storage.root, version.file_path):
                    duplicate_files_deleted += 1
                db.query(models.Alert).filter(models.Alert.document_id == version.document_id).delete(synchronize_session=False)
                db.query(models.SourceStatusSyncLog).filter(models.SourceStatusSyncLog.document_id == version.document_id).delete(synchronize_session=False)
                db.query(models.StandardFileMatch).filter(models.StandardFileMatch.document_id == version.document_id).delete(synchronize_session=False)
                db.query(models.StandardChangeLog).filter(models.StandardChangeLog.document_id == version.document_id).delete(synchronize_session=False)
                db.delete(version)
                duplicate_versions_deleted += 1
                other_versions = (
                    db.query(models.DocumentVersion)
                    .filter(models.DocumentVersion.document_id == version.document_id, models.DocumentVersion.id != version.id)
                    .count()
                )
                if other_versions == 0:
                    document = db.get(models.Document, version.document_id)
                    if document:
                        db.delete(document)
                        duplicate_documents_deleted += 1
        db.commit()

        removed_change_logs = (
            db.query(models.StandardChangeLog)
            .filter(~models.StandardChangeLog.field_name.in_(MONITORED_CHANGE_FIELDS))
            .delete(synchronize_session=False)
        )
        db.commit()

        print("duplicate_versions_deleted", duplicate_versions_deleted)
        print("duplicate_documents_deleted", duplicate_documents_deleted)
        print("duplicate_files_deleted", duplicate_files_deleted)
        print("removed_non_business_change_logs", removed_change_logs)


if __name__ == "__main__":
    main()
