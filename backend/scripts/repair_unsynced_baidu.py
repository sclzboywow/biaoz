#!/usr/bin/env python3
"""Re-download missing local files for unsynced document versions, then upload to Baidu Pan."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
for path in (BACKEND, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from sqlalchemy import text

from app import models
from app.baidu_pan_storage import version_has_baidu_pan
from app.config import get_settings
from app.database import SessionLocal
from app.download_service import check_url_source
from app.settings_store import ensure_default_settings
from app.storage import configured_storage_root
from sync_existing_files_to_baidu_pan import pending_version_ids, sync_one


def main() -> int:
    settings = get_settings()
    redownloaded = 0
    synced = 0
    failed: list[dict] = []

    with SessionLocal() as db:
        ensure_default_settings(db)
        storage_root = configured_storage_root(db, settings.storage_root)
        rows = db.execute(
            text(
                """
                SELECT dv.id, dv.url_source_id, d.standard_no, us.url
                FROM document_versions dv
                JOIN documents d ON d.id = dv.document_id
                LEFT JOIN url_sources us ON us.id = dv.url_source_id
                WHERE dv.is_current = true
                  AND dv.file_path IS NOT NULL AND dv.file_path != ''
                  AND dv.file_path NOT LIKE 'baidupan:%'
                  AND (dv.remark IS NULL OR dv.remark NOT LIKE '%baidu_pan_sync=%')
                ORDER BY dv.id DESC
                """
            )
        ).all()
        print(f"unsynced_versions {len(rows)}")

        for row in rows:
            version = db.get(models.DocumentVersion, row.id)
            if version is None or version_has_baidu_pan(file_path=version.file_path, remark=version.remark):
                continue
            source = db.get(models.UrlSource, row.url_source_id) if row.url_source_id else None
            if source is None or not source.url:
                failed.append({"version_id": row.id, "step": "redownload", "message": "no url_source"})
                print(f"skip redownload version={row.id} no url_source standard={row.standard_no}")
                continue
            try:
                result = check_url_source(db, source, storage_root)
                db.commit()
                if result.ok:
                    redownloaded += 1
                    print(f"redownload ok version={row.id} standard={row.standard_no}")
                else:
                    failed.append({"version_id": row.id, "step": "redownload", "message": result.message})
                    print(f"redownload fail version={row.id} {result.message}")
            except Exception as exc:
                db.rollback()
                failed.append({"version_id": row.id, "step": "redownload", "error": str(exc)[:200]})
                print(f"redownload error version={row.id} {exc}")

    pending = pending_version_ids(limit=max(len(rows), 50), current_only=True)
    print(f"pending_baidu_sync {len(pending)}")
    for version_id in pending:
        result = sync_one(version_id, verify_mode="metadata", update_db=True)
        if result.get("ok"):
            synced += 1
        else:
            failed.append({"version_id": version_id, "step": "baidu_sync", **result})
        print("baidu_sync", json.dumps(result, ensure_ascii=False, default=str))

    summary = {"redownloaded": redownloaded, "synced": synced, "failed": len(failed), "failures": failed[:32]}
    print("repair_unsynced_baidu_summary " + json.dumps(summary, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
