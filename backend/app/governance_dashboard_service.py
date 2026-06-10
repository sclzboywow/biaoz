"""治理运营看板：总览统计、来源健康度、审计日志查询。"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import models
from app.governance_decision_engine import (
    DECISION_AUTO_CONFIRMED,
    DECISION_AUTO_DOWNGRADED,
    DECISION_AUTO_MERGED,
    DECISION_AUTO_REJECTED,
    DECISION_NEED_REVIEW,
    RISK_HIGH,
)
from app.governance_decision_service import governance_supervision_summary
from app.governance_service import governance_dashboard
from app.ocr_download_service import (
    TASK_ARCHIVED,
    TASK_CAPTCHA_FAILED,
    TASK_DOWNLOAD_FAILED,
    TASK_DUPLICATE_FILE,
    TASK_NEED_MANUAL,
    TASK_OCR_FAILED,
    TASK_PDF_INVALID,
    TASK_PENDING,
    TASK_RUNNING,
    TASK_SKIPPED,
    ocr_task_dashboard,
)
from app.source_governance import (
    ALL_GOVERNANCE_STATUSES,
    GOV_BLACKLIST,
    GOV_CLUE_ONLY,
    GOV_HIGH_PRIORITY,
    GOV_INVALID,
    GOV_NEED_OCR,
    GOV_PAUSED,
    GOV_PROFILED,
    is_ungoverned_status,
)


def _today_start() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def governance_dashboard_summary(db: Session) -> dict:
    base = governance_dashboard(db)
    supervision = governance_supervision_summary(db)
    ocr = ocr_task_dashboard(db)
    today = _today_start()

    low_trust = db.scalar(
        select(func.count())
        .select_from(models.UrlSource)
        .where(
            models.UrlSource.is_official_domain.is_(False),
            or_(
                models.UrlSource.source_quality_score.is_(None),
                models.UrlSource.source_quality_score < 50,
            ),
        )
    ) or 0

    need_manual = db.scalar(
        select(func.count())
        .select_from(models.GovernanceDecision)
        .where(models.GovernanceDecision.decision == DECISION_NEED_REVIEW)
    ) or 0
    need_manual += db.scalar(
        select(func.count()).select_from(models.OcrDownloadTask).where(models.OcrDownloadTask.status == TASK_NEED_MANUAL)
    ) or 0

    pdf_invalid_today = db.scalar(
        select(func.count())
        .select_from(models.OcrDownloadTask)
        .where(models.OcrDownloadTask.status == TASK_PDF_INVALID, models.OcrDownloadTask.finished_at >= today)
    ) or 0

    url_type_distribution = {
        row[0] or "unknown": row[1]
        for row in db.execute(
            select(models.UrlSource.url_type, func.count())
            .group_by(models.UrlSource.url_type)
            .order_by(func.count().desc())
        ).all()
    }
    quality_distribution = {
        "high": db.scalar(
            select(func.count()).select_from(models.UrlSource).where(models.UrlSource.source_quality_score >= 80)
        )
        or 0,
        "medium": db.scalar(
            select(func.count())
            .select_from(models.UrlSource)
            .where(models.UrlSource.source_quality_score >= 50, models.UrlSource.source_quality_score < 80)
        )
        or 0,
        "low": db.scalar(
            select(func.count())
            .select_from(models.UrlSource)
            .where(
                or_(models.UrlSource.source_quality_score.is_(None), models.UrlSource.source_quality_score < 50)
            )
        )
        or 0,
    }
    governance_status_distribution = base.get("url_sources", {})
    risk_distribution = {
        "high": supervision.get("high_risk_exceptions", 0),
        "medium": db.scalar(
            select(func.count())
            .select_from(models.GovernanceDecision)
            .where(models.GovernanceDecision.risk_level == "medium")
        )
        or 0,
        "low": db.scalar(
            select(func.count())
            .select_from(models.GovernanceDecision)
            .where(
                or_(models.GovernanceDecision.risk_level == "low", models.GovernanceDecision.risk_level.is_(None))
            )
        )
        or 0,
        "pending_review": need_manual,
    }

    return {
        "url_total": base["total"],
        "profiled_url_count": base["profiled"],
        "ungoverned_url_count": base["unprofiled"],
        "official_source_count": base["official_count"],
        "low_trust_source_count": low_trust,
        "duplicate_url_count": base["duplicate_count"],
        "invalid_url_count": base["invalid_count"],
        "need_ocr_count": base["need_ocr_count"],
        "auto_confirmed_count": supervision.get("auto_confirmed", 0),
        "need_manual_count": need_manual,
        "ocr_success_today": ocr.get("success_today", 0),
        "pdf_invalid_today": pdf_invalid_today,
        "auto_merged_count": supervision.get("auto_merged", 0),
        "auto_downgraded_count": supervision.get("auto_downgraded", 0),
        "pending_alerts": supervision.get("pending_alerts", 0),
        "distributions": {
            "url_type": url_type_distribution,
            "source_quality": quality_distribution,
            "governance_status": governance_status_distribution,
            "risk": risk_distribution,
        },
    }


def _suggest_action(
    *,
    health_score: int,
    governance_status: str,
    conflict_rate: float,
    duplicate_rate: float,
    enabled: bool,
) -> str:
    if not enabled:
        return "已禁用"
    if conflict_rate >= 0.2:
        return "排查冲突"
    if duplicate_rate >= 0.15:
        return "合并重复"
    if governance_status == GOV_NEED_OCR:
        return "推进 OCR"
    if health_score < 50:
        return "降级为线索"
    if health_score >= 85:
        return "维持高优先级"
    return "持续观察"


def _trusted_source_health_row(db: Session, source: models.TrustedSource) -> dict:
    domain = (source.domain or "").lower().strip()
    url_query = select(models.UrlSource)
    if domain:
        url_query = url_query.where(func.lower(models.UrlSource.host).like(f"%{domain}%"))
    urls = list(db.scalars(url_query).all())
    url_total = len(urls) or 1
    normal = sum(1 for item in urls if item.status == models.SourceStatus.normal.value)
    parsed = sum(1 for item in urls if item.governance_status not in {"pending", "profiled", "error", ""})
    pdf_probable = sum(1 for item in urls if item.is_probable_pdf)
    duplicate = sum(1 for item in urls if item.governance_status == "重复待合并")
    need_ocr = sum(1 for item in urls if item.governance_status == GOV_NEED_OCR)

    resources = list(
        db.scalars(select(models.StandardResource).where(models.StandardResource.source_id == source.id)).all()
    )
    resource_total = len(resources) or 1
    with_number = sum(1 for item in resources if item.normalized_standard_no or item.standard_no)
    with_status = sum(1 for item in resources if item.source_status)

    tasks = list(
        db.scalars(select(models.OcrDownloadTask).where(models.OcrDownloadTask.source_id == source.id)).all()
    )
    task_total = len(tasks) or 1
    ocr_success = sum(1 for item in tasks if item.status in {TASK_ARCHIVED, TASK_DUPLICATE_FILE})
    pdf_valid = db.scalar(
        select(func.count())
        .select_from(models.FileObject)
        .join(models.OcrDownloadTask, models.OcrDownloadTask.file_object_id == models.FileObject.id)
        .where(models.OcrDownloadTask.source_id == source.id, models.FileObject.pdf_valid.is_(True))
    ) or 0

    conflict_count = db.scalar(
        select(func.count())
        .select_from(models.GovernanceDecision)
        .join(models.StandardResource, models.StandardResource.id == models.GovernanceDecision.target_id)
        .where(
            models.StandardResource.source_id == source.id,
            models.GovernanceDecision.conflict_count.is_not(None),
            models.GovernanceDecision.conflict_count > 0,
        )
    ) or 0

    health_score = source.source_health_score or source.trust_score or 50
    capture_success_rate = round(normal / url_total * 100, 1)
    number_parse_rate = round(with_number / resource_total * 100, 1)
    status_parse_rate = round(with_status / resource_total * 100, 1)
    pdf_valid_rate = round((pdf_valid / task_total * 100) if tasks else (pdf_probable / url_total * 100), 1)
    ocr_success_rate = round(ocr_success / task_total * 100, 1)
    duplicate_rate = round(duplicate / url_total * 100, 1)
    conflict_rate = round(conflict_count / resource_total * 100, 1)

    return {
        "id": source.id,
        "source_name": source.source_name,
        "source_role": source.source_role,
        "trust_level": source.trust_level,
        "domain": source.domain,
        "health_score": health_score,
        "capture_success_rate": capture_success_rate,
        "number_parse_rate": number_parse_rate,
        "status_parse_rate": status_parse_rate,
        "pdf_valid_rate": pdf_valid_rate,
        "ocr_success_rate": ocr_success_rate,
        "duplicate_rate": duplicate_rate,
        "conflict_rate": conflict_rate,
        "governance_status": source.governance_status,
        "enabled": source.enabled,
        "url_count": len(urls),
        "resource_count": len(resources),
        "need_ocr_count": need_ocr,
        "suggested_action": _suggest_action(
            health_score=health_score,
            governance_status=source.governance_status,
            conflict_rate=conflict_rate / 100,
            duplicate_rate=duplicate_rate / 100,
            enabled=source.enabled,
        ),
    }


def list_source_health_page(
    db: Session,
    *,
    cursor: int | None = None,
    page_size: int = 50,
    trust_level: str | None = None,
    source_role: str | None = None,
    governance_status: str | None = None,
    health_min: int | None = None,
    health_max: int | None = None,
    enabled: bool | None = None,
) -> dict:
    page_size = max(1, min(page_size, 200))
    query = select(models.TrustedSource).order_by(models.TrustedSource.id.desc())
    if cursor:
        query = query.where(models.TrustedSource.id < cursor)
    if trust_level:
        query = query.where(models.TrustedSource.trust_level == trust_level)
    if source_role:
        query = query.where(models.TrustedSource.source_role == source_role)
    if governance_status:
        query = query.where(models.TrustedSource.governance_status == governance_status)
    if enabled is not None:
        query = query.where(models.TrustedSource.enabled.is_(enabled))
    if health_min is not None:
        query = query.where(
            func.coalesce(models.TrustedSource.source_health_score, models.TrustedSource.trust_score) >= health_min
        )
    if health_max is not None:
        query = query.where(
            func.coalesce(models.TrustedSource.source_health_score, models.TrustedSource.trust_score) <= health_max
        )

    rows = db.scalars(query.limit(page_size + 1)).all()
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    items = [_trusted_source_health_row(db, source) for source in rows]
    total = db.scalar(select(func.count()).select_from(models.TrustedSource)) or 0
    return {
        "total": total,
        "items": items,
        "next_cursor": rows[-1].id if has_more and rows else None,
        "has_more": has_more,
    }


def ocr_tasks_summary(db: Session) -> dict:
    dashboard = ocr_task_dashboard(db)
    return {
        **dashboard,
        "pending_ocr": dashboard["pending"],
        "archived": db.scalar(
            select(func.count()).select_from(models.OcrDownloadTask).where(models.OcrDownloadTask.status == TASK_ARCHIVED)
        )
        or 0,
        "ocr_failed": db.scalar(
            select(func.count()).select_from(models.OcrDownloadTask).where(models.OcrDownloadTask.status == TASK_OCR_FAILED)
        )
        or 0,
        "captcha_failed": db.scalar(
            select(func.count())
            .select_from(models.OcrDownloadTask)
            .where(models.OcrDownloadTask.status == TASK_CAPTCHA_FAILED)
        )
        or 0,
        "download_failed": db.scalar(
            select(func.count())
            .select_from(models.OcrDownloadTask)
            .where(models.OcrDownloadTask.status == TASK_DOWNLOAD_FAILED)
        )
        or 0,
        "pdf_invalid": db.scalar(
            select(func.count()).select_from(models.OcrDownloadTask).where(models.OcrDownloadTask.status == TASK_PDF_INVALID)
        )
        or 0,
        "duplicate_file": db.scalar(
            select(func.count())
            .select_from(models.OcrDownloadTask)
            .where(models.OcrDownloadTask.status == TASK_DUPLICATE_FILE)
        )
        or 0,
        "skipped": db.scalar(
            select(func.count()).select_from(models.OcrDownloadTask).where(models.OcrDownloadTask.status == TASK_SKIPPED)
        )
        or 0,
        "running": dashboard["running"],
        "need_manual": dashboard["need_manual"],
        "ocr_success_rate_today": dashboard["ocr_success_rate"],
        "pdf_pass_rate_today": dashboard["pdf_pass_rate"],
    }


def file_objects_summary(db: Session) -> dict:
    total = db.scalar(select(func.count()).select_from(models.FileObject)) or 0
    pdf_valid = db.scalar(
        select(func.count()).select_from(models.FileObject).where(models.FileObject.pdf_valid.is_(True))
    ) or 0
    pdf_invalid = total - pdf_valid
    large_files = db.scalar(
        select(func.count()).select_from(models.FileObject).where(models.FileObject.file_size >= 20 * 1024 * 1024)
    ) or 0
    return {
        "total": total,
        "pdf_valid": pdf_valid,
        "pdf_invalid": pdf_invalid,
        "duplicate_hint": db.scalar(
            select(func.count())
            .select_from(models.OcrDownloadTask)
            .where(models.OcrDownloadTask.status == TASK_DUPLICATE_FILE)
        )
        or 0,
        "large_files": large_files,
        "unlinked": db.scalar(
            select(func.count())
            .select_from(models.FileObject)
            .where(
                ~models.FileObject.id.in_(
                    select(models.DocumentVersion.file_object_id).where(models.DocumentVersion.file_object_id.is_not(None))
                )
            )
        )
        if total
        else 0,
    }


def supervision_summary_enhanced(db: Session) -> dict:
    base = governance_supervision_summary(db)
    return {
        **base,
        "auto_rejected": db.scalar(
            select(func.count())
            .select_from(models.StandardResource)
            .where(models.StandardResource.auto_decision == DECISION_AUTO_REJECTED)
        )
        or 0,
        "status_conflict_count": db.scalar(
            select(func.count())
            .select_from(models.GovernanceDecision)
            .where(
                models.GovernanceDecision.metadata_json.like('%"conflict_type": "a_plus_status_conflict"%')
                | models.GovernanceDecision.metadata_json.like('%"conflict_type": "authority_abolished_local_active"%')
                | models.GovernanceDecision.metadata_json.like('%"conflict_type": "authority_local_status_conflict"%')
            )
        )
        or 0,
        "file_anomaly_count": db.scalar(
            select(func.count())
            .select_from(models.GovernanceDecision)
            .where(
                models.GovernanceDecision.metadata_json.like('%"conflict_type": "pdf_validation_failed"%')
                | models.GovernanceDecision.metadata_json.like('%"conflict_type": "hash_changed_metadata_unchanged"%')
            )
        )
        or 0,
        "ocr_anomaly_count": db.scalar(
            select(func.count())
            .select_from(models.GovernanceDecision)
            .where(models.GovernanceDecision.metadata_json.like('%"conflict_type": "ocr_consecutive_failure"%'))
        )
        or 0
        + (
            db.scalar(
                select(func.count())
                .select_from(models.OcrDownloadTask)
                .where(
                    models.OcrDownloadTask.status.in_(
                        (TASK_OCR_FAILED, TASK_CAPTCHA_FAILED, TASK_DOWNLOAD_FAILED, TASK_PDF_INVALID, TASK_NEED_MANUAL)
                    )
                )
            )
            or 0
        ),
        "need_review_count": base.get("pending_exceptions", 0),
    }


def list_process_audit_logs(
    db: Session,
    *,
    target_type: str | None = None,
    target_id: int | None = None,
    process_type: str | None = None,
    limit: int = 50,
) -> list[dict]:
    limit = max(1, min(limit, 200))
    query = select(models.ProcessAuditLog).order_by(models.ProcessAuditLog.id.desc())
    if target_type:
        query = query.where(models.ProcessAuditLog.target_type == target_type)
    if target_id is not None:
        query = query.where(models.ProcessAuditLog.target_id == target_id)
    if process_type:
        query = query.where(models.ProcessAuditLog.process_type == process_type)
    rows = db.scalars(query.limit(limit)).all()
    return [
        {
            "id": row.id,
            "process_name": row.process_name,
            "process_type": row.process_type,
            "step_name": row.step_name,
            "action": row.action,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "source_id": row.source_id,
            "status": row.status,
            "message": row.message,
            "confidence_score": row.confidence_score,
            "input_summary": row.input_summary,
            "output_summary": row.output_summary,
            "error_message": row.error_message,
            "created_at": row.created_at,
        }
        for row in rows
    ]
