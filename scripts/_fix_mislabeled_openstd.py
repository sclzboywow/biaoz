from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text

from app.database import SessionLocal
from app.gb688_captcha_download import extract_hcno, openstd_download_page_url
from app.samr_std_sync import _download_url

SOURCE_NAME = "国家标准信息公共服务平台（全量）"
PERMANENT_UNAVAILABLE = "文件不可下载"
TEMP_FAILURE = "文件采集失败"


def main() -> None:
    with SessionLocal() as db:
        source = db.execute(
            text("SELECT id FROM trusted_sources WHERE source_name = :name LIMIT 1"),
            {"name": SOURCE_NAME},
        ).first()
        if not source:
            print(json.dumps({"error": "source_not_found"}, ensure_ascii=False))
            return
        sid = source[0]

        mislabeled = db.execute(
            text(
                """
                SELECT sr.id, sr.standard_no, sr.standard_name, sr.sync_status, sr.last_synced_at
                FROM standard_resources sr
                WHERE sr.source_id = :sid
                  AND sr.sync_status = :status
                  AND (
                    sr.summary LIKE '%openstd.samr.gov.cn%'
                    OR sr.summary LIKE '%download_page%'
                    OR sr.pdf_trial_url LIKE '%openstd.samr.gov.cn%'
                    OR sr.detail_url LIKE '%openstd.samr.gov.cn%'
                  )
                ORDER BY sr.id
                """
            ),
            {"sid": sid, "status": PERMANENT_UNAVAILABLE},
        ).all()

        reset_ids: list[int] = []
        kept_ids: list[int] = []
        for row in mislabeled:
            resource_id, standard_no, _name, _status, last_synced_at = row
            resource = db.execute(
                text("SELECT summary, pdf_trial_url, detail_url FROM standard_resources WHERE id = :id"),
                {"id": resource_id},
            ).first()
            hcno = extract_hcno(resource[0], resource[1], resource[2]) if resource else None
            if not hcno:
                kept_ids.append(resource_id)
                continue
            download_url = _download_url(hcno)
            archived = db.execute(
                text(
                    """
                    SELECT 1 FROM url_sources us
                    JOIN document_versions dv ON dv.url_source_id = us.id AND dv.is_current = true
                    WHERE us.url = :url LIMIT 1
                    """
                ),
                {"url": download_url},
            ).first()
            if archived:
                kept_ids.append(resource_id)
                continue
            # Wrongly marked during legacy gb688 fallback window (today)
            if last_synced_at is None or last_synced_at >= datetime.now(UTC) - timedelta(days=2):
                reset_ids.append(resource_id)

        if reset_ids:
            db.execute(
                text("UPDATE standard_resources SET sync_status = NULL WHERE id = ANY(:ids)"),
                {"ids": reset_ids},
            )
            db.commit()

        # Recent openstd archived via captcha flow
        openstd_recent = db.execute(
            text(
                """
                SELECT COUNT(*) FROM document_versions dv
                JOIN url_sources us ON us.id = dv.url_source_id
                WHERE dv.is_current = true
                  AND us.url LIKE 'https://openstd.samr.gov.cn/bzgk/std/showGb?type=download%'
                  AND dv.downloaded_at >= NOW() - INTERVAL '2 days'
                """
            )
        ).scalar() or 0

        openstd_baidu = db.execute(
            text(
                """
                SELECT COUNT(*) FROM document_versions dv
                JOIN url_sources us ON us.id = dv.url_source_id
                WHERE dv.is_current = true
                  AND us.url LIKE 'https://openstd.samr.gov.cn/bzgk/std/showGb?type=download%'
                  AND dv.file_path LIKE 'baidupan:%'
                """
            )
        ).scalar() or 0

        openstd_local_only = db.execute(
            text(
                """
                SELECT COUNT(*) FROM document_versions dv
                JOIN url_sources us ON us.id = dv.url_source_id
                WHERE dv.is_current = true
                  AND us.url LIKE 'https://openstd.samr.gov.cn/bzgk/std/showGb?type=download%'
                  AND dv.file_path NOT LIKE 'baidupan:%'
                """
            )
        ).scalar() or 0

        spc_recent = db.execute(
            text(
                """
                SELECT COUNT(*) FROM document_versions dv
                JOIN url_sources us ON us.id = dv.url_source_id
                WHERE dv.is_current = true
                  AND us.url LIKE 'spc-online-reading://%'
                  AND dv.downloaded_at >= NOW() - INTERVAL '2 days'
                """
            )
        ).scalar() or 0

        spc_baidu = db.execute(
            text(
                """
                SELECT COUNT(*) FROM document_versions dv
                JOIN url_sources us ON us.id = dv.url_source_id
                WHERE dv.is_current = true
                  AND us.url LIKE 'spc-online-reading://%'
                  AND dv.file_path LIKE 'baidupan:%'
                """
            )
        ).scalar() or 0

        spc_local_only = db.execute(
            text(
                """
                SELECT COUNT(*) FROM document_versions dv
                JOIN url_sources us ON us.id = dv.url_source_id
                WHERE dv.is_current = true
                  AND us.url LIKE 'spc-online-reading://%'
                  AND dv.file_path NOT LIKE 'baidupan:%'
                """
            )
        ).scalar() or 0

        all_local_only = db.execute(
            text(
                """
                SELECT COUNT(*) FROM document_versions
                WHERE is_current = true AND file_path NOT LIKE 'baidupan:%'
                """
            )
        ).scalar() or 0

        still_unavailable = db.execute(
            text(
                "SELECT COUNT(*) FROM standard_resources WHERE source_id = :sid AND sync_status = :status"
            ),
            {"sid": sid, "status": PERMANENT_UNAVAILABLE},
        ).scalar() or 0

        print(
            json.dumps(
                {
                    "mislabeled_found": len(mislabeled),
                    "reset_count": len(reset_ids),
                    "reset_ids_sample": reset_ids[:20],
                    "kept_unavailable_count": len(kept_ids),
                    "still_unavailable": still_unavailable,
                    "openstd_archived_total": openstd_baidu + openstd_local_only,
                    "openstd_recent_2d": openstd_recent,
                    "openstd_on_baidu": openstd_baidu,
                    "openstd_local_only": openstd_local_only,
                    "spc_archived_total": spc_baidu + spc_local_only,
                    "spc_recent_2d": spc_recent,
                    "spc_on_baidu": spc_baidu,
                    "spc_local_only": spc_local_only,
                    "all_local_only_current": all_local_only,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
