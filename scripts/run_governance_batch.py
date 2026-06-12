#!/usr/bin/env python3
"""治理自动化批处理：URL 画像 + 标准资源自动决策 + 告警清扫。"""

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

from app.database import SessionLocal  # noqa: E402
from app.governance_automation import sweep_all_auto_resolvable_alerts, sweep_auto_resolvable_alerts  # noqa: E402
from app.governance_decision_service import run_governance_decisions  # noqa: E402
from app.governance_pipeline import sync_pipeline_phase  # noqa: E402
from app.governance_service import profile_url_sources_batch  # noqa: E402
from app.ocr_download_service import create_ocr_tasks_from_decisions  # noqa: E402
from app.post_decision_ingest_service import collect_ingestible_resource_ids, trigger_post_decision_ingest  # noqa: E402
from app.settings_store import ensure_default_settings, get_bool_setting, get_int_setting  # noqa: E402

LOG_DIR = ROOT / "logs"
PROFILE_CURSOR = LOG_DIR / "governance-loop.url-profile.cursor"


def read_cursor(path: Path) -> int:
    if not path.exists():
        return 0
    raw = path.read_text(encoding="utf-8").strip()
    return int(raw) if raw.isdigit() else 0


def write_cursor(path: Path, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(value), encoding="utf-8")


def run_profile_batch(*, limit: int, after_id: int) -> dict:
    with SessionLocal() as db:
        ensure_default_settings(db)
        _, result = profile_url_sources_batch(
            db,
            limit=limit,
            only_ungoverned=True,
            dry_run=False,
            after_id=after_id,
            run_type="governance_loop_profile",
        )
    return result


def run_decisions_batch(*, limit: int) -> dict:
    with SessionLocal() as db:
        ensure_default_settings(db)
        return run_governance_decisions(
            db,
            limit=limit,
            only_unprocessed=True,
            dry_run=False,
        )


def run_alert_sweep(*, limit: int, sweep_all: bool = False) -> dict:
    with SessionLocal() as db:
        if sweep_all:
            stats = sweep_all_auto_resolvable_alerts(
                db,
                batch_limit=limit,
                force_remaining=True,
            )
        else:
            stats = sweep_auto_resolvable_alerts(db, limit=limit)
        db.commit()
        return stats


def run_ocr_tasks_batch(*, limit: int) -> dict:
    with SessionLocal() as db:
        ensure_default_settings(db)
        if not get_bool_setting(db, "ocr_download_enabled", default=True):
            return {"created": 0, "skipped": 0, "message": "ocr_download_enabled=false"}
        return create_ocr_tasks_from_decisions(
            db,
            limit=limit,
            only_unprocessed=True,
            dry_run=False,
        )


def run_pipeline_state() -> dict:
    with SessionLocal() as db:
        ensure_default_settings(db)
        state = sync_pipeline_phase(db)
        db.commit()
        return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Governance automation batch")
    parser.add_argument("--profile-limit", type=int, default=5000)
    parser.add_argument("--decision-limit", type=int, default=5000)
    parser.add_argument("--ocr-task-limit", type=int, default=500)
    parser.add_argument("--alert-sweep-limit", type=int, default=3000)
    parser.add_argument("--alert-sweep-all", action="store_true", help="循环清扫直到无法再自动消警")
    parser.add_argument("--skip-profile", action="store_true")
    parser.add_argument("--skip-decisions", action="store_true")
    parser.add_argument("--skip-ocr-tasks", action="store_true")
    parser.add_argument("--skip-alert-sweep", action="store_true")
    parser.add_argument("--skip-post-decision-ingest", action="store_true")
    parser.add_argument("--force-profile", action="store_true", help="画像阶段完成后仍强制跑 URL 画像")
    args = parser.parse_args()

    summary: dict = {}
    with SessionLocal() as db:
        ensure_default_settings(db)
        pipeline_state = sync_pipeline_phase(db)
        db.commit()
    summary["pipeline"] = pipeline_state
    print("governance_pipeline_state", json.dumps(pipeline_state, ensure_ascii=False))

    skip_profile = args.skip_profile or (bool(pipeline_state.get("profile_complete")) and not args.force_profile)

    if not skip_profile:
        after_id = read_cursor(PROFILE_CURSOR)
        profile_result = run_profile_batch(limit=args.profile_limit, after_id=after_id)
        summary["profile"] = profile_result
        processed = int(profile_result.get("total") or 0)
        last_id = profile_result.get("last_url_source_id")
        if processed > 0 and last_id is not None:
            write_cursor(PROFILE_CURSOR, int(last_id))
        elif processed == 0 and after_id > 0:
            write_cursor(PROFILE_CURSOR, 0)
        print("governance_profile_summary", json.dumps(profile_result, ensure_ascii=False))
        with SessionLocal() as db:
            ensure_default_settings(db)
            pipeline_state = sync_pipeline_phase(db)
            db.commit()
            summary["pipeline"] = pipeline_state
            print("governance_pipeline_state", json.dumps(pipeline_state, ensure_ascii=False))
    else:
        reason = "profile_complete" if pipeline_state.get("profile_complete") else "skip_profile_flag"
        print("governance_profile_skipped", json.dumps({"reason": reason}, ensure_ascii=False))

    if not args.skip_decisions:
        decision_result = run_decisions_batch(limit=args.decision_limit)
        summary["decisions"] = decision_result
        print("governance_decisions_summary", json.dumps(decision_result, ensure_ascii=False))
        if not args.skip_post_decision_ingest:
            with SessionLocal() as db:
                ensure_default_settings(db)
                ingest_ids = collect_ingestible_resource_ids(
                    db,
                    decision_stats=decision_result,
                    run_id=decision_result.get("run_id"),
                )
                ingest_limit = get_int_setting(db, "post_decision_ingest_limit", 50)
                ingest_result = trigger_post_decision_ingest(db, resource_ids=ingest_ids, limit=ingest_limit)
            summary["post_decision_ingest"] = ingest_result
            print("governance_post_decision_ingest_summary", json.dumps(ingest_result, ensure_ascii=False, default=str))

    if not args.skip_ocr_tasks:
        ocr_result = run_ocr_tasks_batch(limit=args.ocr_task_limit)
        summary["ocr_tasks"] = ocr_result
        print("governance_ocr_tasks_summary", json.dumps(ocr_result, ensure_ascii=False))

    if not args.skip_alert_sweep:
        alert_result = run_alert_sweep(limit=args.alert_sweep_limit, sweep_all=args.alert_sweep_all)
        summary["alert_sweep"] = alert_result
        print("governance_alert_sweep_summary", json.dumps(alert_result, ensure_ascii=False))

    print("governance_batch_summary", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
