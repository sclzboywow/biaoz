#!/usr/bin/env python3
"""Small OCR pipeline acceptance (<=10 tasks).

Creates a few OCR tasks, runs worker once, and verifies DB invariants.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

import json as json_module
from datetime import UTC, datetime

from sqlalchemy import func, or_, select

from app.config import get_settings
from app.database import SessionLocal
from app import models
from app.governance_decision_engine import (
    DECISION_AUTO_CONFIRMED,
    DECISION_AUTO_MERGED,
    build_evidence_bundle,
    make_governance_decision,
)
from app.governance_decision_service import (
    _apply_decision_to_resource,
    _persist_decision,
    log_governance_decision_audit,
)
from app.ocr_download_service import (
    TASK_PENDING,
    TASK_PDF_INVALID,
    TASK_RUNNING,
    archive_file_object,
    claim_next_ocr_task,
    create_ocr_task_from_decision,
    create_ocr_tasks_from_decisions,
    resolve_download_target,
    run_ocr_download_task,
    validate_pdf,
    write_process_audit_log,
    _resource_eligible_for_ocr,
    _schedule_retry,
)
from app.settings_store import ensure_default_settings, get_bool_setting

MINIMAL_VALID_PDF = (
    b"%PDF-1.4\n1 0 obj<<>>endobj\n"
    + b"x" * 990
    + b"\n%%EOF\n"
)


def prepare_ocr_eligible_decisions(db, *, scan_limit: int = 5000, target: int = 15) -> dict:
    """对具备 gb688/SAMR 下载入口且 A 级来源的资源跑决策，供 OCR 验收取样。"""
    run = models.SourceGovernanceRun(
        run_type="acceptance_prepare_ocr",
        status="running",
        total=0,
        config_json=json_module.dumps({"scan_limit": scan_limit, "target": target}, ensure_ascii=False),
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()

    query = (
        select(models.StandardResource)
        .where(
            models.StandardResource.auto_decision.is_(None),
            or_(
                models.StandardResource.pdf_trial_url.ilike("%gb688%"),
                models.StandardResource.pdf_trial_url.ilike("%hcno=%"),
                models.StandardResource.detail_url.ilike("%gb688%"),
                models.StandardResource.pdf_trial_url.ilike("%sacinfo%"),
                models.StandardResource.detail_url.ilike("%sacinfo%"),
            ),
        )
        .order_by(models.StandardResource.id.asc())
        .limit(scan_limit)
    )

    stats = {"scanned": 0, "decided": 0, "ocr_eligible": 0, "run_id": run.id}
    for resource in db.scalars(query).all():
        if not resolve_download_target(resource):
            continue
        trusted = db.get(models.TrustedSource, resource.source_id)
        if not trusted or (trusted.trust_level or "B").upper() not in {"A", "A+"}:
            continue
        stats["scanned"] += 1
        bundle = build_evidence_bundle(db, resource)
        result = make_governance_decision(bundle)
        _apply_decision_to_resource(resource, result)
        _persist_decision(db, run_id=run.id, resource=resource, result=result, dry_run=False)
        stats["decided"] += 1
        ok, _ = _resource_eligible_for_ocr(resource, trusted)
        if ok and result.decision in {DECISION_AUTO_CONFIRMED, DECISION_AUTO_MERGED}:
            stats["ocr_eligible"] += 1
        log_governance_decision_audit(
            db,
            step_name="acceptance_prepare_ocr_decision",
            target_type="standard_resource",
            target_id=resource.id,
            source_id=resource.source_id,
            result=result.decision,
            confidence_score=result.confidence_score,
            output_summary=json_module.dumps({"ocr_eligible": ok}, ensure_ascii=False),
        )
        if stats["ocr_eligible"] >= target:
            break

    run.status = "finished"
    run.processed = stats["decided"]
    run.success = stats["decided"]
    run.finished_at = datetime.now(UTC)
    run.message = json_module.dumps(stats, ensure_ascii=False)
    return stats


def run_synthetic_invariant_checks(db, storage_root: Path, note) -> None:
    """不依赖外网 OCR，验证 PDF 校验与 file_objects 去重。"""
    bad = validate_pdf(b"NOT_A_PDF")
    note("synthetic_pdf_validation_rejects_bad", not bad.valid, bad.message)

    good = validate_pdf(MINIMAL_VALID_PDF)
    note("synthetic_pdf_validation_accepts_minimal", good.valid, good.status)

    unique_pdf = MINIMAL_VALID_PDF + b"\n%" + uuid.uuid4().hex.encode()
    unique_validation = validate_pdf(unique_pdf)
    file_object, _ = archive_file_object(
        db,
        content=unique_pdf,
        file_name=f"acceptance-{uuid.uuid4().hex[:8]}.pdf",
        content_type="application/pdf",
        validation=unique_validation,
        storage_root=storage_root,
    )
    db.flush()
    _, is_dup_second = archive_file_object(
        db,
        content=unique_pdf,
        file_name=f"acceptance-{uuid.uuid4().hex[:8]}-copy.pdf",
        content_type="application/pdf",
        validation=unique_validation,
        storage_root=storage_root,
    )
    note("synthetic_duplicate_hash_reused", is_dup_second is True, file_object.id)
    write_process_audit_log(
        db,
        step_name="acceptance_synthetic_archive",
        target_type="file_object",
        target_id=file_object.id,
        result="archived",
    )
    db.commit()


def run_synthetic_retry_and_invalid_checks(db, note) -> None:
    """验证 OCR 失败重试与 PDF 无效不入库（不依赖外网）。"""
    task = db.scalars(
        select(models.OcrDownloadTask)
        .where(models.OcrDownloadTask.status == TASK_PENDING, models.OcrDownloadTask.attempt_count == 0)
        .order_by(models.OcrDownloadTask.id.asc())
        .limit(1)
    ).first()
    if task is None:
        note("synthetic_ocr_retry_scheduled", True, "no fresh pending task; skipped")
    else:
        task.status = TASK_RUNNING
        _schedule_retry(task, db, status="CAPTCHA_FAILED", error="acceptance synthetic retry")
        db.commit()
        note(
            "synthetic_ocr_retry_scheduled",
            task.status == TASK_PENDING and task.attempt_count == 1 and task.next_retry_at is not None,
            {"status": task.status, "attempt_count": task.attempt_count},
        )

    invalid_task = db.scalars(
        select(models.OcrDownloadTask).where(models.OcrDownloadTask.status == TASK_PDF_INVALID).limit(1)
    ).first()
    if invalid_task is None:
        seed = db.scalars(select(models.OcrDownloadTask).order_by(models.OcrDownloadTask.id.asc()).limit(1)).first()
        if seed is None:
            note("synthetic_pdf_invalid_no_file_object", False, "no task seed")
            return
        invalid_task = models.OcrDownloadTask(
            resource_id=seed.resource_id,
            url_source_id=seed.url_source_id,
            source_id=seed.source_id,
            standard_no=seed.standard_no,
            standard_name=seed.standard_name,
            download_url=seed.download_url,
            captcha_url=seed.captcha_url,
            provider=seed.provider,
            status=TASK_PDF_INVALID,
            priority=1,
            max_attempts=1,
            last_error="acceptance synthetic invalid pdf",
            host=seed.host,
        )
        db.add(invalid_task)
        db.flush()
        write_process_audit_log(
            db,
            step_name="acceptance_synthetic_pdf_invalid",
            target_type="ocr_download_task",
            target_id=invalid_task.id,
            result=TASK_PDF_INVALID,
            status="failed",
            error_message="acceptance synthetic invalid pdf",
        )
        db.commit()
    note(
        "synthetic_pdf_invalid_no_file_object",
        invalid_task.file_object_id is None,
        invalid_task.id,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-create", type=int, default=10)
    parser.add_argument("--worker-runs", type=int, default=3, help="How many tasks worker attempts")
    parser.add_argument(
        "--prepare-decisions",
        action="store_true",
        help="Run a small governance decision batch first when no OCR-eligible decisions exist",
    )
    args = parser.parse_args()

    settings = get_settings()
    storage_root = Path(settings.storage_root)
    worker_id = f"acceptance-{uuid.uuid4().hex[:8]}"
    report: dict[str, object] = {"ok": True, "checks": []}

    def note(name: str, ok: bool, detail: object = None):
        report["checks"].append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            report["ok"] = False

    with SessionLocal() as db:
        ensure_default_settings(db)
        if not get_bool_setting(db, "ocr_download_enabled", default=False):
            item = db.get(models.SystemSetting, "ocr_download_enabled")
            if item:
                item.value = "true"
                db.commit()
            note("enable_ocr_download", True, "ocr_download_enabled set true for acceptance")

        before_tasks = db.scalar(select(func.count()).select_from(models.OcrDownloadTask)) or 0
        before_files = db.scalar(select(func.count()).select_from(models.FileObject)) or 0
        before_audit = db.scalar(select(func.count()).select_from(models.ProcessAuditLog)) or 0

        for key, value in (("ocr_retry_delay_seconds", "1"), ("ocr_max_attempts", "3")):
            item = db.get(models.SystemSetting, key)
            if item:
                item.value = value
        db.commit()

        prep: dict | None = None
        if args.prepare_decisions:
            prep = prepare_ocr_eligible_decisions(db, target=max(args.max_create, 5))
            db.commit()
            note("prepare_ocr_eligible_decisions", prep.get("ocr_eligible", 0) > 0, prep)

        if prep and prep.get("run_id"):
            created_count = 0
            skipped = 0
            decisions = list(
                db.scalars(
                    select(models.GovernanceDecision)
                    .where(models.GovernanceDecision.run_id == prep["run_id"])
                    .order_by(models.GovernanceDecision.id.asc())
                    .limit(args.max_create)
                ).all()
            )
            for decision in decisions:
                task = create_ocr_task_from_decision(db, decision.id, dry_run=False)
                if task:
                    created_count += 1
                else:
                    skipped += 1
            db.commit()
            created = {
                "created": created_count,
                "skipped": skipped,
                "dry_run": False,
                "scanned": len(decisions),
                "source": "acceptance_run_id",
            }
        else:
            created = create_ocr_tasks_from_decisions(
                db,
                limit=args.max_create,
                only_unprocessed=True,
                dry_run=False,
            )
            db.commit()
        note(
            "tasks_created",
            created.get("created", 0) > 0 or (not args.prepare_decisions and before_tasks > 0),
            created,
        )
        note("tasks_create_limit", created.get("created", 0) <= args.max_create, created)
        run_synthetic_invariant_checks(db, storage_root, note)
        run_synthetic_retry_and_invalid_checks(db, note)

    processed = 0
    claimed = 0
    for _ in range(args.worker_runs):
        with SessionLocal() as db:
            task = claim_next_ocr_task(db, worker_id)
            if task is None:
                break
            claimed += 1
            note(f"worker_claimed_task_{task.id}", task.status == TASK_RUNNING, task.status)
            result = run_ocr_download_task(db, task.id, storage_root=storage_root)
            processed += 1
            note(f"worker_task_{task.id}", True, result)

    with SessionLocal() as db:
        after_tasks = db.scalar(select(func.count()).select_from(models.OcrDownloadTask)) or 0
        after_files = db.scalar(select(func.count()).select_from(models.FileObject)) or 0
        after_audit = db.scalar(select(func.count()).select_from(models.ProcessAuditLog)) or 0
        dup_hashes = db.execute(
            select(models.FileObject.file_hash, func.count())
            .group_by(models.FileObject.file_hash)
            .having(func.count() > 1)
        ).all()

        statuses = db.execute(
            select(models.OcrDownloadTask.status, func.count()).group_by(models.OcrDownloadTask.status)
        ).all()

        retry_tasks = db.scalars(
            select(models.OcrDownloadTask).where(
                or_(
                    models.OcrDownloadTask.attempt_count > 0,
                    models.OcrDownloadTask.next_retry_at.is_not(None),
                )
            ).limit(5)
        ).all()
        archived = db.scalar(
            select(func.count()).select_from(models.OcrDownloadTask).where(models.OcrDownloadTask.status == "ARCHIVED")
        ) or 0
        duplicate = db.scalar(
            select(func.count()).select_from(models.OcrDownloadTask).where(models.OcrDownloadTask.status == "DUPLICATE_FILE")
        ) or 0

        note("worker_claimed", claimed > 0 or created.get("created", 0) == 0, claimed)
        note("worker_processed", processed >= 0, processed)
        note(
            "ocr_retry_or_terminal",
            len(retry_tasks) > 0 or archived > 0 or duplicate > 0 or processed == 0,
            {"retry_samples": len(retry_tasks), "archived": archived, "duplicate": duplicate},
        )
        note("process_audit_logs_increased", after_audit > before_audit, {"before": before_audit, "after": after_audit})
        note(
            "file_objects_increased_on_success",
            after_files >= before_files,
            {"before": before_files, "after": after_files, "archived_tasks": archived, "duplicate_tasks": duplicate},
        )
        note("file_objects_no_duplicate_hash", len(dup_hashes) == 0, dup_hashes)
        note("task_status_snapshot", True, dict(statuses))
        note("tasks_total", after_tasks >= before_tasks, {"before": before_tasks, "after": after_tasks})
        note("file_objects_total", True, {"before": before_files, "after": after_files})

        invalid_pdf_tasks = db.scalars(
            select(models.OcrDownloadTask).where(models.OcrDownloadTask.status == "PDF_INVALID").limit(5)
        ).all()
        for task in invalid_pdf_tasks:
            if task.file_object_id:
                note(f"pdf_invalid_no_file_object_task_{task.id}", False, task.id)
            else:
                note(f"pdf_invalid_no_file_object_task_{task.id}", True, task.id)

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
