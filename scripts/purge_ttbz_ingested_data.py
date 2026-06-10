"""Remove TTBZ archived PDFs and related url_sources/documents from local storage."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from sqlalchemy import text  # noqa: E402

from app import models  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.storage import check_storage_root  # noqa: E402

TTBZ_URL_PATTERN = "https://www.ttbz.org.cn/standardDetail/%"
ADAPTER_KEY = "samr_group_standard_public"
RESET_SYNC_STATUS = "文件采集失败"


def safe_delete_file(storage_root: Path, relative_path: str | None) -> bool:
    if not relative_path or relative_path.startswith("baidupan:"):
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


def purge_ttbz_ingested(*, dry_run: bool, disable_source: bool) -> dict:
    settings = get_settings()
    stats = {
        "url_sources": 0,
        "document_versions": 0,
        "documents": 0,
        "files_deleted": 0,
        "resources_reset": 0,
        "source_disabled": False,
    }

    with SessionLocal() as db:
        storage = check_storage_root(db, settings.storage_root)
        if not storage.available:
            raise SystemExit(f"storage unavailable: {storage.message}")

        source_rows = db.execute(
            text(
                """
                SELECT us.id, us.url
                FROM url_sources us
                WHERE us.url LIKE :pattern
                ORDER BY us.id
                """
            ),
            {"pattern": TTBZ_URL_PATTERN},
        ).all()
        stats["url_sources"] = len(source_rows)

        version_ids: list[int] = []
        document_ids: list[int] = []
        file_paths: list[str] = []
        detail_urls: list[str] = []

        for source_id, source_url in source_rows:
            detail_urls.append(str(source_url))
            versions = (
                db.query(models.DocumentVersion)
                .filter(models.DocumentVersion.url_source_id == source_id)
                .order_by(models.DocumentVersion.id)
                .all()
            )
            for version in versions:
                version_ids.append(version.id)
                document_ids.append(version.document_id)
                file_paths.append(version.file_path)

        stats["document_versions"] = len(version_ids)
        stats["documents"] = len(set(document_ids))

        if dry_run:
            stats["files_deleted"] = sum(
                1
                for file_path in file_paths
                if file_path and not str(file_path).startswith("baidupan:")
            )
            if disable_source:
                source = db.query(models.TrustedSource).filter(models.TrustedSource.adapter_key == ADAPTER_KEY).first()
                stats["source_disabled"] = bool(source and source.enabled)
            if detail_urls:
                stats["resources_reset"] = db.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM standard_resources sr
                        JOIN trusted_sources ts ON ts.id = sr.source_id
                        WHERE ts.adapter_key = :adapter_key
                          AND sr.detail_url = ANY(:urls)
                          AND sr.sync_status = '已同步'
                        """
                    ),
                    {"adapter_key": ADAPTER_KEY, "urls": detail_urls},
                ).scalar()
            return stats

        for file_path in file_paths:
            if safe_delete_file(storage.root, file_path):
                stats["files_deleted"] += 1

        if version_ids:
            doc_id_set = set(document_ids)
            db.query(models.StandardEvidence).filter(models.StandardEvidence.document_id.in_(doc_id_set)).delete(
                synchronize_session=False
            )
            db.query(models.DocumentTag).filter(models.DocumentTag.document_id.in_(doc_id_set)).delete(
                synchronize_session=False
            )
            db.query(models.Alert).filter(models.Alert.document_id.in_(doc_id_set)).delete(
                synchronize_session=False
            )
            db.query(models.SourceStatusSyncLog).filter(
                models.SourceStatusSyncLog.document_id.in_(set(document_ids))
            ).delete(synchronize_session=False)
            db.query(models.StandardFileMatch).filter(
                models.StandardFileMatch.document_id.in_(set(document_ids))
            ).delete(synchronize_session=False)
            db.query(models.StandardChangeLog).filter(
                models.StandardChangeLog.document_id.in_(set(document_ids))
            ).delete(synchronize_session=False)
            db.query(models.ProjectDocument).filter(
                models.ProjectDocument.document_id.in_(set(document_ids))
            ).delete(synchronize_session=False)
            db.query(models.DocumentVersion).filter(models.DocumentVersion.id.in_(version_ids)).delete(
                synchronize_session=False
            )

        for document_id in sorted(set(document_ids)):
            remaining = (
                db.query(models.DocumentVersion).filter(models.DocumentVersion.document_id == document_id).count()
            )
            if remaining == 0:
                document = db.get(models.Document, document_id)
                if document:
                    db.delete(document)

        source_ids = [row[0] for row in source_rows]
        if source_ids:
            db.query(models.CheckLog).filter(models.CheckLog.url_source_id.in_(source_ids)).delete(
                synchronize_session=False
            )
            db.query(models.Alert).filter(models.Alert.url_source_id.in_(source_ids)).delete(synchronize_session=False)
            db.query(models.UrlSource).filter(models.UrlSource.id.in_(source_ids)).delete(synchronize_session=False)

        if detail_urls:
            result = db.execute(
                text(
                    """
                    UPDATE standard_resources sr
                    SET sync_status = :reset_status,
                        last_synced_at = NOW()
                    FROM trusted_sources ts
                    WHERE ts.id = sr.source_id
                      AND ts.adapter_key = :adapter_key
                      AND sr.detail_url = ANY(:urls)
                      AND sr.sync_status = '已同步'
                    """
                ),
                {
                    "adapter_key": ADAPTER_KEY,
                    "urls": detail_urls,
                    "reset_status": RESET_SYNC_STATUS,
                },
            )
            stats["resources_reset"] = int(result.rowcount or 0)

        if disable_source:
            source = db.query(models.TrustedSource).filter(models.TrustedSource.adapter_key == ADAPTER_KEY).first()
            if source and source.enabled:
                source.enabled = False
                source.remark = (
                    (source.remark or "").strip()
                    + "；团体标准正文采集已停用（会员账户锁定，2026-06-08 清理入库文件）"
                ).strip("；")
                stats["source_disabled"] = True

        db.commit()

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge TTBZ ingested PDF archives from local storage/DB.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-source-enabled", action="store_true", help="Do not disable samr_group_standard_public")
    args = parser.parse_args()

    stats = purge_ttbz_ingested(dry_run=args.dry_run, disable_source=not args.keep_source_enabled)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
