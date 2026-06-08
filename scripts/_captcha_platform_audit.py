from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text

from app.database import SessionLocal


def main() -> None:
    with SessionLocal() as db:
        sources = db.execute(
            text(
                """
                SELECT ts.id, ts.source_name, ts.adapter_key, COUNT(sr.id) AS resource_count
                FROM trusted_sources ts
                LEFT JOIN standard_resources sr ON sr.source_id = ts.id
                WHERE ts.adapter_key IN (
                    'samr_industry_standard_public',
                    'samr_local_standard_public',
                    'samr_gb_all_public',
                    'samr_std_public'
                )
                GROUP BY ts.id, ts.source_name, ts.adapter_key
                ORDER BY ts.id
                """
            )
        ).all()

        portal_candidates = db.execute(
            text(
                """
                SELECT ts.adapter_key, COUNT(*) AS cnt
                FROM standard_resources sr
                JOIN trusted_sources ts ON ts.id = sr.source_id
                WHERE ts.adapter_key IN ('samr_industry_standard_public', 'samr_local_standard_public')
                  AND (
                    sr.pdf_trial_url LIKE '%sacinfo.org.cn%'
                    OR sr.detail_url LIKE '%sacinfo.org.cn%'
                  )
                  AND sr.sync_status IS DISTINCT FROM '文件不可下载'
                GROUP BY ts.adapter_key
                """
            )
        ).all()

        archived = db.execute(
            text(
                """
                SELECT
                  CASE
                    WHEN us.url LIKE 'https://openstd.samr.gov.cn/bzgk/std/showGb?type=download%' THEN 'openstd'
                    WHEN us.url LIKE 'https://hbba.sacinfo.org.cn/portal/online/%' THEN 'hbba_portal'
                    WHEN us.url LIKE 'https://dbba.sacinfo.org.cn/portal/online/%' THEN 'dbba_portal'
                    WHEN us.url LIKE 'https://%bba.sacinfo.org.cn/portal/download/%' THEN 'sacinfo_download_token'
                    WHEN us.url LIKE 'spc-online-reading://%' THEN 'spc'
                    ELSE 'other'
                  END AS channel,
                  COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE dv.file_path LIKE 'baidupan:%') AS on_baidu
                FROM document_versions dv
                JOIN url_sources us ON us.id = dv.url_source_id
                WHERE dv.is_current = true
                GROUP BY 1
                ORDER BY total DESC
                """
            )
        ).all()

        storage_backend = db.execute(
            text("SELECT value FROM system_settings WHERE key = 'storage_backend'")
        ).scalar()

        print(
            json.dumps(
                {
                    "storage_backend": storage_backend,
                    "trusted_sources": [
                        {"id": r[0], "name": r[1], "adapter_key": r[2], "resources": r[3]} for r in sources
                    ],
                    "portal_candidates": {r[0]: r[1] for r in portal_candidates},
                    "archived_by_channel": [
                        {"channel": r[0], "total": r[1], "on_baidu": r[2]} for r in archived
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
