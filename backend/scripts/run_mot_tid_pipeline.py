#!/usr/bin/env python3
"""Quick MOT tid sync + discovery smoke test."""
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
        setting = db.get(models.SystemSetting, "batch2_file_ingest_enabled")
        if setting and setting.value.lower() != "true":
            setting.value = "true"
        ingest = db.get(models.SystemSetting, "ingest_enabled")
        if ingest and ingest.value.lower() != "true":
            ingest.value = "true"
        db.commit()

    import subprocess

    sync = subprocess.run(
        [
            sys.executable,
            "scripts/sync_batch2_trusted_sources.py",
            "--include-disabled",
            "--pages",
            "2",
            "--adapter-key",
            ADAPTER_KEY,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    print(sync.stdout)
    if sync.returncode != 0:
        print(sync.stderr)
        return sync.returncode

    with SessionLocal() as db:
        source = db.query(models.TrustedSource).filter(models.TrustedSource.adapter_key == ADAPTER_KEY).first()
        if source is None:
            print("source_not_found")
            return 1
        source_id = source.id
        storage_root = configured_storage_root(db, settings.storage_root)
        before = status_counts(db, source_id)
        samples = db.scalars(
            select(models.StandardResource)
            .where(models.StandardResource.source_id == source_id)
            .order_by(models.StandardResource.id.desc())
            .limit(5)
        ).all()
        sample_rows = [
            {
                "standard_no": row.standard_no,
                "detail_url": row.detail_url,
                "status": row.file_ingest_status,
                "official_file_url": row.official_file_url,
            }
            for row in samples
        ]

    with SessionLocal() as db:
        discovery = discover_files_for_source(db, source_id=source_id, limit=120, only_missing=True)
        after_discovery = status_counts(db, source_id)
        candidates = list_batch2_ingest_candidates(db, source_id=source_id, limit=5)
        ingest_results = []
        for candidate in candidates:
            row = db.get(models.StandardResource, candidate.id)
            if row is None:
                continue
            ingest_results.append(
                ingest_batch2_resource_file(db, row, storage_root=storage_root, defer_baidu_upload=True)
            )
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

    report = {
        "before": before,
        "discovery": discovery,
        "after_discovery": after_discovery,
        "samples": sample_rows,
        "ingest": ingest_results,
        "after_ingest": after_ingest,
        "admitted": admitted,
        "file_ready": file_ready,
    }
    print("mot_tid_pipeline", json.dumps(report, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
