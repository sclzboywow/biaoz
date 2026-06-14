from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT if (ROOT / "app").is_dir() else ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app import models
from app.batch2_admission import BATCH2_STANDARD_BODY_ADAPTER_KEYS, FILE_INGEST_ADMITTED
from app.batch2_file_ingest_service import ingest_batch2_resource_file, list_batch2_ingest_candidates
from app.database import SessionLocal
from app.settings_store import ensure_default_settings, ensure_default_trusted_sources
from app.storage import configured_storage_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest verified batch-2 standard body files into formal library")
    parser.add_argument("--source-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--only-resource-ids", default="")
    parser.add_argument("--defer-baidu-upload", action="store_true")
    args = parser.parse_args()

    resource_ids = [int(item) for item in args.only_resource_ids.split(",") if item.strip().isdigit()]

    with SessionLocal() as db:
        storage_root = configured_storage_root(db)
        ensure_default_settings(db)
        ensure_default_trusted_sources(db)
        if args.source_id:
            source_ids = [args.source_id]
        else:
            source_ids = [
                row.id
                for row in db.query(models.TrustedSource)
                .filter(models.TrustedSource.adapter_key.in_(BATCH2_STANDARD_BODY_ADAPTER_KEYS))
                .all()
            ]

    summary = {"sources": len(source_ids), "ingested": 0, "failed": 0, "results": []}
    for source_id in source_ids:
        with SessionLocal() as db:
            candidates = list_batch2_ingest_candidates(
                db,
                source_id=source_id,
                limit=args.limit,
                resource_ids=resource_ids or None,
            )
        for resource in candidates:
            with SessionLocal() as db:
                row = db.get(models.StandardResource, resource.id)
                if row is None or row.file_ingest_status == FILE_INGEST_ADMITTED:
                    continue
                outcome = ingest_batch2_resource_file(
                    db,
                    row,
                    storage_root=storage_root,
                    defer_baidu_upload=args.defer_baidu_upload,
                )
            summary["results"].append({"resource_id": resource.id, **outcome})
            if outcome.get("ok"):
                summary["ingested"] += 1
            else:
                summary["failed"] += 1

    print("batch2_file_ingest_summary", json.dumps(summary, ensure_ascii=False, default=str))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
