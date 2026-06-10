from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from sqlalchemy import text

from app.database import SessionLocal


def iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def main() -> int:
    now = datetime.now(UTC)
    out: dict = {"generated_at": now.isoformat()}

    with SessionLocal() as db:
        sources = db.execute(
            text(
                """
                SELECT
                  ts.id,
                  ts.source_name,
                  ts.adapter_key,
                  ts.enabled,
                  ts.crawl_frequency,
                  (SELECT COUNT(*) FROM standard_resources sr WHERE sr.source_id = ts.id) AS resource_count,
                  (SELECT MAX(sr.last_synced_at) FROM standard_resources sr WHERE sr.source_id = ts.id) AS last_resource_sync,
                  (SELECT MAX(sr.created_at) FROM standard_resources sr WHERE sr.source_id = ts.id) AS last_resource_created,
                  (SELECT COUNT(*) FROM standard_resources sr
                     WHERE sr.source_id = ts.id AND sr.last_synced_at > NOW() - INTERVAL '7 days') AS synced_7d,
                  (SELECT COUNT(*) FROM standard_resources sr
                     WHERE sr.source_id = ts.id AND sr.created_at > NOW() - INTERVAL '7 days') AS created_7d,
                  (SELECT COUNT(*) FROM standard_resources sr
                     WHERE sr.source_id = ts.id AND sr.created_at > NOW() - INTERVAL '30 days') AS created_30d
                FROM trusted_sources ts
                ORDER BY ts.id
                """
            )
        ).mappings().all()
        out["trusted_sources"] = [
            {k: iso(v) if k.endswith("_at") or k.startswith("last_") else v for k, v in dict(row).items()}
            for row in sources
        ]

        out["newest_resources"] = [
            dict(row)
            for row in db.execute(
                text(
                    """
                    SELECT sr.id, ts.adapter_key, sr.standard_no, sr.sync_status,
                           sr.created_at, sr.last_synced_at
                    FROM standard_resources sr
                    JOIN trusted_sources ts ON ts.id = sr.source_id
                    ORDER BY sr.created_at DESC
                    LIMIT 20
                    """
                )
            ).mappings().all()
        ]
        for row in out["newest_resources"]:
            row["created_at"] = iso(row.get("created_at"))
            row["last_synced_at"] = iso(row.get("last_synced_at"))

        out["source_categories"] = [
            dict(row)
            for row in db.execute(
                text(
                    """
                    SELECT ts.adapter_key, sc.category_name, sc.sync_status,
                           sc.last_sync_started_at, sc.last_sync_finished_at, sc.last_sync_error,
                           sc.last_synced_page, sc.resource_count
                    FROM source_categories sc
                    JOIN trusted_sources ts ON ts.id = sc.source_id
                    ORDER BY sc.last_sync_finished_at DESC NULLS LAST
                    LIMIT 30
                    """
                )
            ).mappings().all()
        ]
        for row in out["source_categories"]:
            for key in ("last_sync_started_at", "last_sync_finished_at"):
                row[key] = iso(row.get(key))

        out["daily_new_resources"] = [
            dict(row)
            for row in db.execute(
                text(
                    """
                    SELECT DATE(sr.created_at AT TIME ZONE 'Asia/Shanghai') AS day,
                           ts.adapter_key,
                           COUNT(*) AS cnt
                    FROM standard_resources sr
                    JOIN trusted_sources ts ON ts.id = sr.source_id
                    WHERE sr.created_at > NOW() - INTERVAL '30 days'
                    GROUP BY 1, 2
                    ORDER BY 1 DESC, 2
                    """
                )
            ).mappings().all()
        ]
        for row in out["daily_new_resources"]:
            row["day"] = iso(row.get("day"))

        out["daily_new_total"] = [
            dict(row)
            for row in db.execute(
                text(
                    """
                    SELECT DATE(created_at AT TIME ZONE 'Asia/Shanghai') AS day, COUNT(*) AS cnt
                    FROM standard_resources
                    WHERE created_at > NOW() - INTERVAL '30 days'
                    GROUP BY 1
                    ORDER BY 1 DESC
                    """
                )
            ).mappings().all()
        ]
        for row in out["daily_new_total"]:
            row["day"] = iso(row.get("day"))

        out["samr_source_categories"] = [
            dict(row)
            for row in db.execute(
                text(
                    """
                    SELECT ts.adapter_key, sc.category_name, sc.sync_status,
                           sc.last_sync_finished_at, sc.last_sync_error, sc.last_synced_page
                    FROM source_categories sc
                    JOIN trusted_sources ts ON ts.id = sc.source_id
                    WHERE ts.adapter_key IN (
                      'samr_industry_standard_public',
                      'samr_local_standard_public',
                      'samr_gb_all_public',
                      'samr_enterprise_standard_public',
                      'guobiao_ebook'
                    )
                    ORDER BY sc.last_sync_finished_at DESC NULLS LAST
                    LIMIT 20
                    """
                )
            ).mappings().all()
        ]
        for row in out["samr_source_categories"]:
            row["last_sync_finished_at"] = iso(row.get("last_sync_finished_at"))

        out["document_versions_recent"] = db.execute(
            text(
                """
                SELECT COUNT(*) AS cnt_7d
                FROM document_versions
                WHERE downloaded_at > NOW() - INTERVAL '7 days'
                """
            )
        ).scalar()

    log_dir = ROOT / "logs"
    pid_checks = [
        "trusted-sources-loop.pid",
        "spc-metadata-slices-loop.pid",
        "spc-advanced-metadata-loop.pid",
        "ingest-monitor.pid",
        "openstd-file-loop.pid",
        "sacinfo-portal-industry-file-loop.pid",
        "sacinfo-portal-local-file-loop.pid",
    ]
    workers: list[dict] = []
    for name in pid_checks:
        path = log_dir / name
        pid = None
        alive = False
        if path.exists():
            raw = path.read_text(encoding="utf-8").strip()
            if raw.isdigit():
                pid = int(raw)
                try:
                    os.kill(pid, 0)
                    alive = True
                except OSError:
                    alive = False
        workers.append({"name": name.replace(".pid", ""), "pid": pid, "alive": alive})

    monitor_log = log_dir / "ingest-monitor.log"
    if monitor_log.exists():
        lines = monitor_log.read_text(encoding="utf-8", errors="replace").splitlines()
        out["ingest_monitor_tail"] = lines[-25:]
    else:
        out["ingest_monitor_tail"] = []

    trusted_log = log_dir / "trusted-sources-loop.out.log"
    if trusted_log.exists():
        lines = trusted_log.read_text(encoding="utf-8", errors="replace").splitlines()
        out["trusted_sources_loop_tail"] = lines[-20:]
    else:
        out["trusted_sources_loop_tail"] = []

    out["workers"] = workers
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
