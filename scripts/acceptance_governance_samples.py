#!/usr/bin/env python3
"""Governance sample dry-run acceptance (no full batch).

Runs four sample types with limit=1000 dry_run and prints aggregated metrics.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.database import SessionLocal
from app.governance_dashboard_service import governance_dashboard_summary
from app.governance_service import run_sample_profiling
from app.settings_store import ensure_default_settings, ensure_default_trusted_sources

SAMPLES = ("official_domains", "pdf_links", "cloud_drive", "commercial_sites")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true", default=True)
    args = parser.parse_args()

    results: dict[str, dict] = {}
    with SessionLocal() as db:
        ensure_default_settings(db)
        ensure_default_trusted_sources(db)
        for sample in SAMPLES:
            result = run_sample_profiling(db, sample_type=sample, limit=args.limit, dry_run=args.dry_run)
            results[sample] = result
            print(f"\n--- sample={sample} ---")
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

        summary = governance_dashboard_summary(db)
        url_type_dist = summary.get("distributions", {}).get("url_type", {})
        gov_status_dist = summary.get("distributions", {}).get("governance_status", {})

    agg = {
        "samples": results,
        "url_type_distribution": url_type_dist,
        "governance_status_distribution": gov_status_dist,
        "need_ocr_count": summary.get("need_ocr_count"),
        "high_priority_from_samples": sum(r.get("high_priority_count", 0) for r in results.values()),
        "clue_only_from_samples": sum(r.get("clue_only_count", 0) for r in results.values()),
        "blacklist_candidate_from_samples": sum(r.get("blacklist_candidate_count", 0) for r in results.values()),
        "dashboard_need_ocr": summary.get("need_ocr_count"),
        "dashboard_auto_confirmed": summary.get("auto_confirmed_count"),
    }
    print("\n=== Aggregated acceptance output ===")
    print(json.dumps(agg, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
