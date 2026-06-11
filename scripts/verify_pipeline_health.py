#!/usr/bin/env python3
"""检查治理 + 入库流水线 worker 是否在跑。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
LOG_DIR = ROOT / "logs"
os.environ.setdefault("INGEST_LOG_ROOT", str(LOG_DIR))
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.database import SessionLocal  # noqa: E402
from app.governance_pipeline import sync_pipeline_phase  # noqa: E402
from app.ingest_runtime import ingest_runtime_summary  # noqa: E402
from app.settings_store import ensure_default_settings, get_bool_setting  # noqa: E402

CRITICAL_WORKERS = (
    "governance_loop",
    "trusted_sources",
    "spc_metadata",
    "ocr_worker",
    "openstd",
    "spc_online",
)


def main() -> int:
    with SessionLocal() as db:
        ensure_default_settings(db)
        pipeline = sync_pipeline_phase(db)
        runtime = ingest_runtime_summary(db, interval_minutes=30)
        settings = {
            "ingest_enabled": get_bool_setting(db, "ingest_enabled", default=False),
            "ocr_download_enabled": get_bool_setting(db, "ocr_download_enabled", default=True),
        }
        db.commit()

    workers = {item["key"]: item for item in runtime["workers"]}
    issues: list[str] = []
    worker_report: dict[str, dict] = {}

    for key in CRITICAL_WORKERS:
        item = workers.get(key)
        if item is None:
            issues.append(f"missing worker spec: {key}")
            continue
        worker_report[key] = {
            "status": item["status"],
            "pid": item.get("pid"),
            "pid_alive": item.get("pid_alive"),
            "message": item.get("status_message"),
        }
        if item["status"] == "stopped":
            issues.append(f"{key} stopped")

    report = {
        "ok": not issues,
        "issues": issues,
        "settings": settings,
        "pipeline": pipeline,
        "workers": worker_report,
        "status_counts": runtime.get("status_counts"),
    }
    print("pipeline_health", json.dumps(report, ensure_ascii=False, default=str))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
