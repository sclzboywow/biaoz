#!/usr/bin/env python3
"""Run MOT batch-2 file discovery + ingest verification in container."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT if (ROOT / "app").is_dir() else ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from sqlalchemy import func, select

from app import models
from app.batch2_admission import FILE_INGEST_ADMITTED, FILE_INGEST_FILE_READY
from app.batch2_file_ingest_service import discover_files_for_source, ingest_batch2_resource_file, list_batch2_ingest_candidates
from app.config import get_settings
from app.database import SessionLocal
from app.settings_store import ensure_default_settings, get_bool_setting
from app.storage import configured_storage_root

ADAPTER_KEY = "mot_transport_standard_public"


def _status_counts(db, source_id: int) -> dict[str, int]:
    rows = db.execute(
        select(models.StandardResource.file_ingest_status, func.count())
        .where(models.StandardResource.source_id == source_id)
        .group_by(models.StandardResource.file_ingest_status)
    ).all()
    return {str(status or "null"): count for status, count in rows}


def main() -> int:
    settings = get_settings()
    report: dict = {"steps": []}
    with SessionLocal() as db:
        ensure_default_settings(db)
        source = db.query(models.TrustedSource).filter(models.TrustedSource.adapter_key == ADAPTER_KEY).first()
        if source is None:
            print("mot_pipeline_verify", json.dumps({"error": "source_not_found"}, ensure_ascii=False))
            return 1

        setting = db.get(models.SystemSetting, "batch2_file_ingest_enabled")
        if setting and setting.value.lower() != "true":
            setting.value = "true"
            db.commit()
            report["steps"].append("enabled_batch2_file_ingest")

        report["before_status"] = _status_counts(db, source.id)
        source_id = source.id
        storage_root = configured_storage_root(db, settings.storage_root)

    with SessionLocal() as db:
        discovery = discover_files_for_source(db, source_id=source_id, limit=80, only_missing=True)
        db.commit()
        report["discovery"] = discovery
        source = db.get(models.TrustedSource, source_id)
        report["after_discovery_status"] = _status_counts(db, source_id)

        candidates = list_batch2_ingest_candidates(db, source_id=source_id, limit=5)
        ingest_results = []
        for candidate in candidates:
            row = db.get(models.StandardResource, candidate.id)
            if row is None:
                continue
            outcome = ingest_batch2_resource_file(db, row, storage_root=storage_root, defer_baidu_upload=True)
            ingest_results.append({"resource_id": row.id, "standard_no": row.standard_no, **outcome})
        report["ingest"] = ingest_results
        report["after_ingest_status"] = _status_counts(db, source_id)
        report["file_ready_remaining"] = db.scalar(
            select(func.count())
            .select_from(models.StandardResource)
            .where(
                models.StandardResource.source_id == source_id,
                models.StandardResource.file_ingest_status == FILE_INGEST_FILE_READY,
            )
        )
        report["admitted_count"] = db.scalar(
            select(func.count())
            .select_from(models.StandardResource)
            .where(
                models.StandardResource.source_id == source_id,
                models.StandardResource.file_ingest_status == FILE_INGEST_ADMITTED,
            )
        )
        report["ingest_enabled"] = get_bool_setting(db, "ingest_enabled", False)
        report["batch2_file_ingest_enabled"] = get_bool_setting(db, "batch2_file_ingest_enabled", True)

    print("mot_pipeline_verify", json.dumps(report, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
