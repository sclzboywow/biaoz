#!/usr/bin/env python3
from pathlib import Path

from sqlalchemy import text

from app.config import get_settings
from app.database import SessionLocal
from app.settings_store import ensure_default_settings, get_setting


def main() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        ensure_default_settings(db)
        root = Path(get_setting(db, "storage_root", settings.storage_root))
        stats = db.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM documents) AS documents,
                  (SELECT COUNT(*) FROM document_versions WHERE is_current = true) AS current_versions,
                  (SELECT COUNT(*) FROM document_versions dv WHERE dv.is_current = true
                     AND (dv.file_path LIKE 'baidupan:%' OR dv.remark LIKE '%baidu_pan_sync=%')) AS on_baidu
                """
            )
        ).mappings().one()
        rows = db.execute(
            text(
                """
                SELECT id, file_path
                FROM document_versions
                WHERE is_current = true
                  AND file_path NOT LIKE 'baidupan:%'
                  AND (remark IS NULL OR remark NOT LIKE '%baidu_pan_sync=%')
                  AND file_path IS NOT NULL AND file_path != ''
                ORDER BY id DESC
                """
            )
        ).all()
        found = 0
        missing: list[tuple[int, str]] = []
        for vid, fp in rows:
            path = Path(fp) if Path(fp).is_absolute() else root / fp
            if path.exists() and path.is_file():
                found += 1
            else:
                missing.append((vid, fp))
        print("documents", stats["documents"])
        print("current_versions", stats["current_versions"])
        print("on_baidu", stats["on_baidu"])
        print("unsynced_total", len(rows))
        print("unsynced_local_found", found)
        print("unsynced_local_missing", len(missing))
        pct = round(int(stats["on_baidu"]) / int(stats["current_versions"]) * 100, 3) if stats["current_versions"] else 0
        print("sync_rate_pct", pct)
        for vid, fp in missing[:10]:
            print("MISSING", vid, fp)


if __name__ == "__main__":
    main()
