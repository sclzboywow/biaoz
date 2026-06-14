#!/usr/bin/env python3
"""Remove stale MOT standard_resources and reset captcha-blocked manual_review rows."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from sqlalchemy import delete, func, or_, select

from app import models
from app.batch2_admission import FILE_INGEST_FILE_READY, FILE_INGEST_MANUAL_REVIEW
from app.database import SessionLocal

MOT_BASE = "https://jtst.mot.gov.cn"
ADAPTER_KEY = "mot_transport_standard_public"
VALID_DETAIL_PARTS = ("/gb/search/gbDetailed", "/hb/search/stdHBDetailed", "/gfs/search/gfsDetailed")


def _is_dirty_detail_url(detail_url: str | None) -> bool:
    url = (detail_url or "").strip()
    if not url:
        return True
    normalized = url.rstrip("/")
    if normalized == MOT_BASE:
        return True
    return not any(part in url for part in VALID_DETAIL_PARTS)


def _delete_resource_graph(db, resource_id: int) -> None:
    db.execute(delete(models.StandardEvidence).where(models.StandardEvidence.standard_resource_id == resource_id))
    db.execute(delete(models.StandardDetail).where(models.StandardDetail.standard_resource_id == resource_id))
    db.execute(delete(models.StandardFileMatch).where(models.StandardFileMatch.standard_resource_id == resource_id))
    db.execute(delete(models.StandardChangeLog).where(models.StandardChangeLog.standard_resource_id == resource_id))
    db.execute(delete(models.SourceStatusSyncLog).where(models.SourceStatusSyncLog.standard_resource_id == resource_id))
    db.execute(
        delete(models.StandardRelation).where(
            or_(
                models.StandardRelation.current_standard_resource_id == resource_id,
                models.StandardRelation.related_standard_resource_id == resource_id,
            )
        )
    )
    db.execute(delete(models.StandardResource).where(models.StandardResource.id == resource_id))


def main() -> int:
    report: dict = {"deleted": [], "reset_manual_review": 0}
    with SessionLocal() as db:
        source = db.query(models.TrustedSource).filter(models.TrustedSource.adapter_key == ADAPTER_KEY).first()
        if source is None:
            print(json.dumps({"error": "source_not_found"}, ensure_ascii=False))
            return 1

        rows = list(
            db.scalars(
                select(models.StandardResource).where(models.StandardResource.source_id == source.id)
            ).all()
        )
        good_ids = {row.id for row in rows if not _is_dirty_detail_url(row.detail_url)}
        dirty_rows = [row for row in rows if _is_dirty_detail_url(row.detail_url)]

        for row in dirty_rows:
            duplicate = row.standard_no and any(
                other.id != row.id
                and other.id in good_ids
                and other.standard_no == row.standard_no
                for other in rows
            )
            if duplicate or _is_dirty_detail_url(row.detail_url):
                _delete_resource_graph(db, row.id)
                report["deleted"].append(
                    {
                        "id": row.id,
                        "standard_no": row.standard_no,
                        "detail_url": row.detail_url,
                        "reason": "duplicate_dirty" if duplicate else "invalid_detail_url",
                    }
                )

        reset_rows = db.scalars(
            select(models.StandardResource).where(
                models.StandardResource.source_id == source.id,
                models.StandardResource.file_ingest_status == FILE_INGEST_MANUAL_REVIEW,
                models.StandardResource.official_file_url.isnot(None),
            )
        ).all()
        for row in reset_rows:
            summary = row.summary or ""
            if "验证码" in summary or "download_failed" in summary or "openstd" in summary.lower():
                row.file_ingest_status = FILE_INGEST_FILE_READY
                row.summary = summary.replace("[manual_review:", "[retry_ready:")[:2000]
                report["reset_manual_review"] += 1

        db.commit()
        remaining = db.execute(
            select(models.StandardResource.file_ingest_status, func.count())
            .where(models.StandardResource.source_id == source.id)
            .group_by(models.StandardResource.file_ingest_status)
        ).all()
        report["status_after"] = {str(k or "null"): v for k, v in remaining}
        report["remaining_total"] = db.query(models.StandardResource).filter_by(source_id=source.id).count()

    print("mot_cleanup", json.dumps(report, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
