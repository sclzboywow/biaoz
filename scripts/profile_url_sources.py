"""
批量执行 URL 来源画像任务（第二阶段 source_governance）。

用法:
  backend/.venv/Scripts/python.exe scripts/profile_url_sources.py --dry-run --limit 100
  backend/.venv/Scripts/python.exe scripts/profile_url_sources.py --limit 1000
  backend/.venv/Scripts/python.exe scripts/profile_url_sources.py --loop --batch-size 2000
  backend/.venv/Scripts/python.exe scripts/profile_url_sources.py --sample official_domains --limit 1000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.database import SessionLocal
from app.governance_service import (
    governance_summary,
    profile_trusted_sources,
    profile_url_sources_batch,
    run_sample_profiling,
)
from app.settings_store import ensure_default_settings, ensure_default_trusted_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile existing UrlSource records for data governance.")
    parser.add_argument("--limit", "--batch-size", dest="limit", type=int, default=2000)
    parser.add_argument("--after-id", type=int, default=0)
    parser.add_argument("--only-pending", action="store_true", default=True)
    parser.add_argument("--all", dest="only_pending", action="store_false")
    parser.add_argument("--skip-trusted-sources", action="store_true")
    parser.add_argument("--loop", action="store_true", help="Keep running batches until no pending rows remain.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--sample",
        choices=("official_domains", "pdf_links", "cloud_drive", "commercial_sites", "unknown"),
        help="Run sample profiling for a specific URL category.",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        ensure_default_settings(db)
        ensure_default_trusted_sources(db)

        if args.sample:
            result = run_sample_profiling(
                db,
                sample_type=args.sample,
                limit=args.limit,
                dry_run=args.dry_run,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0

        if args.dry_run and not args.loop:
            _, result = profile_url_sources_batch(
                db,
                limit=args.limit,
                only_ungoverned=args.only_pending,
                after_id=args.after_id,
                dry_run=True,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0

        if not args.skip_trusted_sources:
            trusted_count = profile_trusted_sources(db)
            db.commit()
            print(f"trusted_sources_profiled={trusted_count}")

        after_id = args.after_id
        total_success = 0
        total_failed = 0
        while True:
            _, result = profile_url_sources_batch(
                db,
                limit=args.limit,
                only_ungoverned=args.only_pending,
                after_id=after_id,
                dry_run=False,
            )
            total_success += result["profiled"]
            total_failed += result.get("failed", 0)
            print(json.dumps(result, ensure_ascii=False, default=str))
            if not args.loop or result["total"] == 0:
                break
            last_id = db.execute(
                __import__("sqlalchemy").text(
                    "SELECT MAX(id) FROM url_sources WHERE id > :after_id "
                    "AND governance_status NOT IN ('pending', 'profiled', 'error')"
                ),
                {"after_id": after_id},
            ).scalar()
            if last_id is None or last_id <= after_id:
                break
            after_id = int(last_id)
            time.sleep(0.2)

        print(json.dumps({"success": total_success, "failed": total_failed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
