#!/usr/bin/env python3
"""Full MOT batch-2 file discovery + ingest for all file_ready candidates."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from sqlalchemy import func, select

from app import models
from app.batch2_admission import FILE_INGEST_ADMITTED, FILE_INGEST_FILE_READY
from app.batch2_file_ingest_service import discover_files_for_source, ingest_batch2_resource_file, list_batch2_ingest_candidates
from app.config import get_settings
from app.database import SessionLocal
from app.settings_store import ensure_default_settings
from app.storage import configured_storage_root

ADAPTER_KEY = "mot_transport_standard_public"


def status_counts(db, source_id: int) -> dict[str, int]:
    rows = db.execute(
        select(models.StandardResource.file_ingest_status, func.count())
        .where(models.StandardResource.source_id == source_id)
        .group_by(models.StandardResource.file_ingest_status)
    ).all()
    return {str(status or "null"): count for status, count in rows}


def main() -> int:
    settings = get_settings()
    with SessionLocal() as db:
        ensure_default_settings(db)
        for key in ("batch2_file_ingest_enabled", "ingest_enabled"):
            setting = db.get(models.SystemSetting, key)
            if setting and setting.value.lower() != "true":
                setting.value = "true"
        db.commit()
        source = db.query(models.TrustedSource).filter(models.TrustedSource.adapter_key == ADAPTER_KEY).first()
        if source is None:
            print("mot_full_ingest", json.dumps({"error": "source_not_found"}, ensure_ascii=False))
            return 1
        source_id = source.id
        before = status_counts(db, source_id)
        storage_root = configured_storage_root(db, settings.storage_root)

    with SessionLocal() as db:
        discovery = discover_files_for_source(db, source_id=source_id, limit=200, only_missing=True)
        after_discovery = status_counts(db, source_id)

    ingest_results: list[dict] = []
    rounds = 0
    while rounds < 50:
        with SessionLocal() as db:
            candidates = list_batch2_ingest_candidates(db, source_id=source_id, limit=100)
        if not candidates:
            break
        rounds += 1
        for candidate in candidates:
            with SessionLocal() as db:
                row = db.get(models.StandardResource, candidate.id)
                if row is None or row.file_ingest_status != FILE_INGEST_FILE_READY:
                    continue
                outcome = ingest_batch2_resource_file(
                    db,
                    row,
                    storage_root=storage_root,
                    defer_baidu_upload=True,
                )
                ingest_results.append(
                    {
                        "standard_no": row.standard_no,
                        "official_file_url": row.official_file_url,
                        **outcome,
                    }
                )

    with SessionLocal() as db:
        after_ingest = status_counts(db, source_id)
        admitted = db.scalar(
            select(func.count())
            .select_from(models.StandardResource)
            .where(
                models.StandardResource.source_id == source_id,
                models.StandardResource.file_ingest_status == FILE_INGEST_ADMITTED,
            )
        )
        file_ready = db.scalar(
            select(func.count())
            .select_from(models.StandardResource)
            .where(
                models.StandardResource.source_id == source_id,
                models.StandardResource.file_ingest_status == FILE_INGEST_FILE_READY,
            )
        )

    ok_count = sum(1 for item in ingest_results if item.get("ok"))
    report = {
        "before": before,
        "discovery": discovery,
        "after_discovery": after_discovery,
        "rounds": rounds,
        "attempted": len(ingest_results),
        "ingested_this_run": ok_count,
        "failed_this_run": len(ingest_results) - ok_count,
        "ingest": ingest_results,
        "after_ingest": after_ingest,
        "admitted_total": admitted,
        "file_ready_remaining": file_ready,
    }
    print("mot_full_ingest", json.dumps(report, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
