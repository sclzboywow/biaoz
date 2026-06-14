#!/usr/bin/env python3
"""Summarize MOT batch-2 file discovery and ingest status."""
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
from app.database import SessionLocal

ADAPTER_KEY = "mot_transport_standard_public"


def main() -> None:
    with SessionLocal() as db:
        source = db.query(models.TrustedSource).filter(models.TrustedSource.adapter_key == ADAPTER_KEY).first()
        if source is None:
            print("mot_verify", json.dumps({"error": "source_not_found"}, ensure_ascii=False))
            return
        rows = db.execute(
            select(models.StandardResource.file_ingest_status, func.count())
            .where(models.StandardResource.source_id == source.id)
            .group_by(models.StandardResource.file_ingest_status)
        ).all()
        status_counts = {str(status or "null"): count for status, count in rows}
        samples = list(
            db.scalars(
                select(models.StandardResource)
                .where(models.StandardResource.source_id == source.id)
                .order_by(models.StandardResource.id.desc())
                .limit(8)
            )
        )
        admitted = db.scalar(
            select(func.count())
            .select_from(models.StandardResource)
            .where(
                models.StandardResource.source_id == source.id,
                models.StandardResource.file_ingest_status == "admitted",
            )
        )
        docs = db.scalar(
            select(func.count(func.distinct(models.DocumentVersion.id)))
            .select_from(models.DocumentVersion)
            .join(models.UrlSource, models.UrlSource.id == models.DocumentVersion.url_source_id)
            .join(models.StandardResource, models.StandardResource.source_id == source.id)
            .where(models.UrlSource.remark.ilike("%batch2_file_ingest%"))
        )
        print(
            "mot_verify",
            json.dumps(
                {
                    "source_id": source.id,
                    "total_resources": sum(status_counts.values()),
                    "file_ingest_status": status_counts,
                    "admitted_count": admitted,
                    "batch2_document_versions": docs,
                    "samples": [
                        {
                            "id": r.id,
                            "standard_no": r.standard_no,
                            "name": (r.standard_name or "")[:60],
                            "file_ingest_status": r.file_ingest_status,
                            "official_file_url": (r.official_file_url or "")[:100] or None,
                            "detail_url": (r.detail_url or "")[:80] or None,
                        }
                        for r in samples
                    ],
                },
                ensure_ascii=False,
            ),
        )


if __name__ == "__main__":
    main()
