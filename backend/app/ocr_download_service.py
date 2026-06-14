"""受控 OCR 下载、PDF 校验、文件对象归档与标准资源关联。"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app import models
from app.alerts import upsert_pending_alert
from app.batch2_admission import (
    FILE_INGEST_FILE_READY,
    evaluate_batch2_file_admission,
    record_batch2_file_evidence_only,
    resolve_batch2_download_target,
    should_block_batch2_formal_file_ingest,
)
from app.config import get_settings
from app.download_service import (
    DownloadedContent,
    archive_object_relative_path,
    configured_storage_backend,
    doc_type,
    guess_file_name,
    sha256_bytes,
)
from app.gb688_captcha_download import (
    OPENSTD_STD_BASE,
    OpenstdCaptchaError,
    OpenstdCaptchaIncorrectError,
    OpenstdDownloadUnavailableError,
    download_openstd_pdf,
    extract_hcno,
    openstd_download_page_url,
    solve_captcha_image,
)
from app.governance_decision_engine import DECISION_AUTO_CONFIRMED, DECISION_AUTO_MERGED
from app.samr_portal_captcha_download import (
    SamrPortalCaptchaError,
    SamrPortalCaptchaIncorrectError,
    download_sacinfo_portal_pdf,
    extract_portal_base_url,
    extract_portal_pk,
)
from app.settings_store import get_bool_setting, get_int_setting
from app.standard_number import normalize_standard_no
from app.status_calibration import match_resource_to_documents
from app.storage import check_storage_root, relative_storage_path

PROCESS_TYPE = "OCR_DOWNLOAD"

TASK_PENDING = "PENDING"
TASK_RUNNING = "RUNNING"
TASK_OCR_FAILED = "OCR_FAILED"
TASK_CAPTCHA_FAILED = "CAPTCHA_FAILED"
TASK_DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
TASK_PDF_INVALID = "PDF_INVALID"
TASK_DUPLICATE_FILE = "DUPLICATE_FILE"
TASK_ARCHIVED = "ARCHIVED"
TASK_SKIPPED = "SKIPPED"
TASK_NEED_MANUAL = "NEED_MANUAL"

ACTIVE_TASK_STATUSES = {TASK_PENDING, TASK_RUNNING}
TERMINAL_TASK_STATUSES = {
    TASK_ARCHIVED,
    TASK_DUPLICATE_FILE,
    TASK_SKIPPED,
    TASK_NEED_MANUAL,
    TASK_PDF_INVALID,
}

MIN_PDF_BYTES = 1024
MAX_PDF_BYTES = 200 * 1024 * 1024


@dataclass
class PdfValidationResult:
    valid: bool
    status: str
    page_count: int | None = None
    title: str | None = None
    message: str | None = None


def write_process_audit_log(
    db: Session,
    *,
    step_name: str,
    target_type: str | None = None,
    target_id: int | None = None,
    source_id: int | None = None,
    result: str = "ok",
    confidence_score: int | None = None,
    input_summary: str | None = None,
    output_summary: str | None = None,
    error_message: str | None = None,
    status: str = "ok",
) -> models.ProcessAuditLog:
    row = models.ProcessAuditLog(
        process_name="ocr_download",
        process_type=PROCESS_TYPE,
        step_name=step_name,
        action=step_name,
        target_type=target_type,
        target_id=target_id,
        source_id=source_id,
        status=status,
        message=result,
        confidence_score=confidence_score,
        input_summary=input_summary,
        output_summary=output_summary,
        error_message=error_message,
        detail_json=json.dumps(
            {"result": result, "error_message": error_message},
            ensure_ascii=False,
        ),
    )
    db.add(row)
    return row


def _normalize_host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return None


def _similarity(left: str | None, right: str | None) -> int:
    return int(SequenceMatcher(None, (left or "").strip(), (right or "").strip()).ratio() * 100)


def _ocr_download_target_sql_clause():
    """SQL 粗筛：资源可能具备 openstd hcno 或 sacinfo portal 下载入口。"""
    return or_(
        models.StandardResource.summary.ilike("%hcno=%"),
        models.StandardResource.detail_url.ilike("%hcno=%"),
        models.StandardResource.pdf_trial_url.ilike("%hcno=%"),
        models.StandardResource.detail_url.ilike("%/portal/online/%"),
        models.StandardResource.pdf_trial_url.ilike("%/portal/online/%"),
        models.StandardResource.detail_url.ilike("%openstd.samr.gov.cn%"),
        models.StandardResource.pdf_trial_url.ilike("%openstd.samr.gov.cn%"),
    )


ANNOUNCEMENT_RESOURCE_TYPES = (
    "标准公告",
    "征求意见",
    "废止目录",
    "标准计划",
    "政策通知",
    "工业和信息化标准增强",
)


def _ocr_eligible_resource_sql_clause():
    return and_(
        models.StandardResource.auto_decision.in_((DECISION_AUTO_CONFIRMED, DECISION_AUTO_MERGED)),
        models.StandardResource.confidence_score.is_not(None),
        models.StandardResource.confidence_score >= 85,
        or_(models.StandardResource.risk_level.is_(None), models.StandardResource.risk_level != "high"),
        or_(
            models.StandardResource.resource_type.is_(None),
            models.StandardResource.resource_type.notin_(ANNOUNCEMENT_RESOURCE_TYPES),
        ),
        or_(
            _ocr_download_target_sql_clause(),
            and_(
                models.StandardResource.file_ingest_status == FILE_INGEST_FILE_READY,
                models.StandardResource.official_file_url.isnot(None),
            ),
        ),
    )


def resolve_download_target(resource: models.StandardResource) -> dict | None:
    batch2_target = resolve_batch2_download_target(resource)
    if batch2_target:
        return batch2_target
    portal_pk = extract_portal_pk(resource.pdf_trial_url, resource.detail_url, resource.source_book_id)
    portal_base = extract_portal_base_url(resource.pdf_trial_url, resource.detail_url)
    if portal_pk and portal_base:
        return {
            "provider": "samr_portal",
            "download_url": f"{portal_base}/portal/online/{portal_pk}",
            "captcha_url": f"{portal_base}/portal/validate-code?pk={portal_pk}",
            "host": _normalize_host(portal_base),
            "portal_pk": portal_pk,
            "portal_base": portal_base,
        }
    hcno = extract_hcno(resource.pdf_trial_url, resource.summary, resource.detail_url)
    if hcno:
        download_url = openstd_download_page_url(hcno)
        return {
            "provider": "gb688",
            "download_url": download_url,
            "captcha_url": f"{OPENSTD_STD_BASE}/gc",
            "host": _normalize_host(download_url),
            "hcno": hcno,
        }
    return None


def _resource_eligible_for_ocr(
    db: Session,
    resource: models.StandardResource,
    trusted: models.TrustedSource | None,
) -> tuple[bool, str]:
    blocked, reason = should_block_batch2_formal_file_ingest(db, resource=resource, trusted_source=trusted)
    if blocked:
        return False, reason
    if resource.auto_decision not in {DECISION_AUTO_CONFIRMED, DECISION_AUTO_MERGED}:
        return False, f"auto_decision={resource.auto_decision}"
    if (resource.confidence_score or 0) < 85:
        return False, "confidence_score<85"
    if resource.risk_level == "high":
        return False, "risk_level=high"
    level = (trusted.trust_level if trusted else "B").upper()
    if level not in {"A", "A+"}:
        return False, f"trust_level={level}"
    if not resolve_download_target(resource):
        return False, "no_download_target"
    return True, "ok"


def create_or_get_ocr_url_source(db: Session, resource: models.StandardResource, download_url: str) -> models.UrlSource:
    source = db.scalars(select(models.UrlSource).where(models.UrlSource.url == download_url)).first()
    if source:
        return source
    source = models.UrlSource(
        url=download_url,
        source_name=resource.standard_name or resource.standard_no or download_url,
        source_unit=resource.source_name,
        source_type="官方标准PDF",
        category=resource.resource_type or "标准资源",
        check_frequency="manual",
        status=models.SourceStatus.normal.value,
        remark=f"standard_no={resource.standard_no or ''}; standard_resource_id={resource.id}; captcha=ocr_worker",
    )
    db.add(source)
    db.flush()
    return source


def create_ocr_task_from_decision(db: Session, decision_id: int, *, dry_run: bool = False) -> models.OcrDownloadTask | None:
    decision = db.get(models.GovernanceDecision, decision_id)
    if decision is None or decision.target_type != "standard_resource":
        raise ValueError("decision not found or not a standard_resource decision")
    resource = db.get(models.StandardResource, decision.target_id)
    if resource is None:
        raise ValueError("standard resource not found")

    existing = db.scalars(
        select(models.OcrDownloadTask).where(
            models.OcrDownloadTask.resource_id == resource.id,
            models.OcrDownloadTask.status.in_(tuple(ACTIVE_TASK_STATUSES | {TASK_ARCHIVED, TASK_DUPLICATE_FILE})),
        )
    ).first()
    if existing:
        return None

    trusted = db.get(models.TrustedSource, resource.source_id)
    ok, reason = _resource_eligible_for_ocr(db, resource, trusted)
    if not ok:
        write_process_audit_log(
            db,
            step_name="create_ocr_task_from_decision",
            target_type="governance_decision",
            target_id=decision_id,
            source_id=resource.source_id,
            result="skipped",
            input_summary=json.dumps({"resource_id": resource.id}, ensure_ascii=False),
            output_summary=reason,
        )
        return None

    target = resolve_download_target(resource)
    assert target is not None
    max_attempts = get_int_setting(db, "ocr_max_attempts", default=3)
    priority = min(100, max(10, (resource.confidence_score or 50) + (10 if (trusted and trusted.trust_level == "A+") else 0)))

    if dry_run:
        write_process_audit_log(
            db,
            step_name="create_ocr_task_from_decision",
            target_type="governance_decision",
            target_id=decision_id,
            source_id=resource.source_id,
            result="dry_run",
            input_summary=json.dumps({"resource_id": resource.id, "provider": target["provider"]}, ensure_ascii=False),
        )
        return None

    url_source = create_or_get_ocr_url_source(db, resource, target["download_url"])
    task = models.OcrDownloadTask(
        resource_id=resource.id,
        url_source_id=url_source.id,
        source_id=resource.source_id,
        standard_no=resource.standard_no,
        standard_name=resource.standard_name,
        download_url=target["download_url"],
        captcha_url=target["captcha_url"],
        provider=target["provider"],
        status=TASK_PENDING,
        priority=priority,
        max_attempts=max_attempts,
        decision_id=decision.id,
        host=target.get("host"),
    )
    db.add(task)
    db.flush()
    write_process_audit_log(
        db,
        step_name="create_ocr_task_from_decision",
        target_type="ocr_download_task",
        target_id=task.id,
        source_id=resource.source_id,
        result="created",
        input_summary=json.dumps({"decision_id": decision_id, "resource_id": resource.id}, ensure_ascii=False),
    )
    return task


def create_ocr_tasks_from_decisions(
    db: Session,
    *,
    limit: int = 100,
    source_id: int | None = None,
    only_unprocessed: bool = True,
    dry_run: bool = False,
) -> dict:
    if not get_bool_setting(db, "ocr_download_enabled", default=True):
        return {"created": 0, "skipped": 0, "dry_run": dry_run, "message": "ocr_download_enabled=false"}

    query = (
        select(models.GovernanceDecision, models.StandardResource)
        .join(models.StandardResource, models.StandardResource.id == models.GovernanceDecision.target_id)
        .join(models.TrustedSource, models.TrustedSource.id == models.StandardResource.source_id)
        .where(
            models.GovernanceDecision.target_type == "standard_resource",
            models.GovernanceDecision.decision.in_((DECISION_AUTO_CONFIRMED, DECISION_AUTO_MERGED)),
            models.TrustedSource.trust_level.in_(("A", "A+")),
            _ocr_eligible_resource_sql_clause(),
        )
        .order_by(models.GovernanceDecision.decided_at.desc(), models.GovernanceDecision.id.desc())
    )
    if source_id is not None:
        query = query.where(models.StandardResource.source_id == source_id)
    if only_unprocessed:
        subq = select(models.OcrDownloadTask.resource_id).where(
            models.OcrDownloadTask.resource_id.is_not(None),
            models.OcrDownloadTask.status.in_(tuple(ACTIVE_TASK_STATUSES | {TASK_ARCHIVED, TASK_DUPLICATE_FILE})),
        )
        query = query.where(models.StandardResource.id.notin_(subq))

    scan_limit = max(1, min(limit, 5000))
    rows = db.execute(query.limit(scan_limit)).all()
    created = 0
    skipped = 0
    for decision, _resource in rows:
        task = create_ocr_task_from_decision(db, decision.id, dry_run=dry_run)
        if task:
            created += 1
        else:
            skipped += 1
    if not dry_run:
        db.commit()
    else:
        db.rollback()
    return {
        "created": created,
        "skipped": skipped,
        "dry_run": dry_run,
        "scanned": len(rows),
        "scan_order": "recent_first",
    }


def _host_running_count(db: Session, host: str | None) -> int:
    if not host:
        return 0
    return (
        db.scalar(
            select(func.count())
            .select_from(models.OcrDownloadTask)
            .where(models.OcrDownloadTask.status == TASK_RUNNING, models.OcrDownloadTask.host == host)
        )
        or 0
    )


def _source_hourly_count(db: Session, source_id: int | None) -> int:
    """Count download attempts for a source in the last hour (not task creations)."""
    if not source_id:
        return 0
    since = datetime.now(UTC) - timedelta(hours=1)
    return (
        db.scalar(
            select(func.count())
            .select_from(models.OcrDownloadTask)
            .where(
                models.OcrDownloadTask.source_id == source_id,
                models.OcrDownloadTask.started_at.is_not(None),
                models.OcrDownloadTask.started_at >= since,
            )
        )
        or 0
    )


def release_stale_ocr_tasks(db: Session) -> int:
    """Re-queue or fail OCR tasks stuck in RUNNING after worker crash/timeout."""
    stale_seconds = max(60, get_int_setting(db, "ocr_task_stale_seconds", default=900))
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
    stale_tasks = list(
        db.scalars(
            select(models.OcrDownloadTask).where(
                models.OcrDownloadTask.status == TASK_RUNNING,
                models.OcrDownloadTask.locked_at.is_not(None),
                models.OcrDownloadTask.locked_at < cutoff,
            )
        )
    )
    if not stale_tasks:
        return 0

    released = 0
    for task in stale_tasks:
        task.attempt_count += 1
        stale_note = f"任务超时释放（>{stale_seconds}s，worker={task.locked_by or '-'}）"
        task.last_error = f"{task.last_error}; {stale_note}" if task.last_error else stale_note
        if task.attempt_count >= task.max_attempts:
            task.status = TASK_NEED_MANUAL
            task.finished_at = datetime.now(UTC)
            result = "need_manual"
        else:
            task.status = TASK_PENDING
            task.next_retry_at = datetime.now(UTC)
            result = "pending"
        task.locked_by = None
        task.locked_at = None
        write_process_audit_log(
            db,
            step_name="release_stale_ocr_task",
            target_type="ocr_download_task",
            target_id=task.id,
            source_id=task.source_id,
            result=result,
            output_summary=stale_note,
        )
        released += 1
    db.commit()
    return released


def _ocr_host_limit_reached(db: Session, host: str | None, host_limit: int) -> bool:
    if host_limit <= 0 or not host:
        return False
    return _host_running_count(db, host) >= host_limit


def _ocr_source_hourly_limit_reached(db: Session, source_id: int | None, source_hourly_limit: int) -> bool:
    if source_hourly_limit <= 0 or not source_id:
        return False
    return _source_hourly_count(db, source_id) >= source_hourly_limit


def claim_next_ocr_task(db: Session, worker_id: str) -> models.OcrDownloadTask | None:
    release_stale_ocr_tasks(db)
    host_limit = get_int_setting(db, "ocr_host_concurrency", default=0)
    source_hourly_limit = get_int_setting(db, "ocr_source_hourly_limit", default=0)
    now = datetime.now(UTC)
    scan_limit = 500 if host_limit > 0 or source_hourly_limit > 0 else 100

    candidates = db.scalars(
        select(models.OcrDownloadTask)
        .where(
            models.OcrDownloadTask.status == TASK_PENDING,
            or_(models.OcrDownloadTask.next_retry_at.is_(None), models.OcrDownloadTask.next_retry_at <= now),
        )
        .order_by(models.OcrDownloadTask.priority.desc(), models.OcrDownloadTask.id.asc())
        .limit(scan_limit)
    ).all()

    for task in candidates:
        if _ocr_host_limit_reached(db, task.host, host_limit):
            continue
        if _ocr_source_hourly_limit_reached(db, task.source_id, source_hourly_limit):
            continue
        task.status = TASK_RUNNING
        task.locked_by = worker_id
        task.locked_at = now
        task.started_at = now
        db.flush()
        write_process_audit_log(
            db,
            step_name="claim_next_ocr_task",
            target_type="ocr_download_task",
            target_id=task.id,
            source_id=task.source_id,
            result="claimed",
            output_summary=worker_id,
        )
        db.commit()
        db.refresh(task)
        return task
    return None


def fetch_captcha(task: models.OcrDownloadTask, *, timeout_seconds: int = 60) -> tuple[bytes, str]:
    if not task.captcha_url:
        raise OpenstdCaptchaError("任务缺少 captcha_url")
    with httpx.Client(follow_redirects=True, timeout=timeout_seconds) as client:
        response = client.get(
            task.captcha_url,
            headers={
                "User-Agent": "Mozilla/5.0 StandardDocsOCR/1.0",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": task.download_url or "",
            },
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type") or "image/jpeg"
        return response.content, content_type


def solve_captcha_by_ocr(image_bytes: bytes) -> str:
    return solve_captcha_image(image_bytes)


def submit_captcha_and_download(task: models.OcrDownloadTask, db: Session) -> DownloadedContent:
    from app.download_service import fetch_url

    resource = db.get(models.StandardResource, task.resource_id) if task.resource_id else None
    max_attempts = task.max_attempts or get_int_setting(db, "ocr_max_attempts", default=3)
    remaining = max(1, max_attempts - task.attempt_count)

    if task.provider == "batch2_direct":
        url_source = db.get(models.UrlSource, task.url_source_id) if task.url_source_id else None
        if url_source is None and task.download_url and resource:
            url_source = create_or_get_ocr_url_source(db, resource, task.download_url)
            task.url_source_id = url_source.id
        if url_source is None:
            raise OpenstdDownloadUnavailableError("batch2_direct 缺少下载来源")
        return fetch_url(url_source, timeout_seconds=120)

    if task.provider == "samr_portal" and resource:
        portal_pk = extract_portal_pk(resource.pdf_trial_url, resource.detail_url, resource.source_book_id)
        portal_base = extract_portal_base_url(resource.pdf_trial_url, resource.detail_url)
        if not portal_pk or not portal_base:
            raise SamrPortalCaptchaError("缺少 portal pk/base")
        return download_sacinfo_portal_pdf(portal_base, portal_pk, max_attempts=remaining)

    hcno = None
    if resource:
        hcno = extract_hcno(resource.pdf_trial_url, resource.summary, resource.detail_url)
    if not hcno and task.download_url:
        hcno = extract_hcno(task.download_url)
    if not hcno:
        raise OpenstdDownloadUnavailableError("缺少 hcno")
    return download_openstd_pdf(hcno, max_attempts=remaining)


def validate_pdf(content: bytes, *, content_type: str | None = None) -> PdfValidationResult:
    if not content.startswith(b"%PDF"):
        return PdfValidationResult(valid=False, status="invalid_header", message="文件头不是 %PDF")
    if len(content) < MIN_PDF_BYTES:
        return PdfValidationResult(valid=False, status="too_small", message="文件过小")
    if len(content) > MAX_PDF_BYTES:
        return PdfValidationResult(valid=False, status="too_large", message="文件过大")
    tail = content[-4096:]
    if b"%%EOF" not in tail:
        return PdfValidationResult(valid=False, status="missing_eof", message="文件尾缺少 %%EOF")
    if content_type and "pdf" not in content_type.lower() and "octet-stream" not in content_type.lower():
        return PdfValidationResult(valid=False, status="bad_content_type", message=f"Content-Type 异常：{content_type}")

    page_count = content.count(b"/Type /Page") + content.count(b"/Type/Page")
    title = None
    title_match = re.search(rb"/Title\s*\(([^)]+)\)", content[:8192])
    if title_match:
        title = title_match.group(1).decode("utf-8", errors="ignore")[:500]

    return PdfValidationResult(
        valid=True,
        status="valid",
        page_count=page_count or None,
        title=title,
    )


def archive_file_object(
    db: Session,
    *,
    content: bytes,
    file_name: str,
    content_type: str | None,
    validation: PdfValidationResult,
    storage_root: Path,
) -> tuple[models.FileObject, bool]:
    file_hash = sha256_bytes(content)
    existing = db.scalars(select(models.FileObject).where(models.FileObject.file_hash == file_hash)).first()
    if existing:
        return existing, True

    storage_backend = configured_storage_backend(db)
    relative_path = archive_object_relative_path(file_hash, file_name)
    local_path = None
    baidu_uri = None
    storage_path = relative_path

    if storage_backend in {"local", "dual"}:
        storage_status = check_storage_root(db, storage_root)
        if storage_status and storage_status.available:
            target = storage_status.root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            local_path = relative_storage_path(storage_status.root, target)

    file_object = models.FileObject(
        file_hash=file_hash,
        content_hash=file_hash,
        file_size=len(content),
        file_ext=Path(file_name).suffix.lower().lstrip(".") or "pdf",
        mime_type=content_type or "application/pdf",
        storage_backend=storage_backend,
        storage_path=storage_path,
        local_path=local_path,
        baidu_pan_uri=baidu_uri,
        pdf_valid=validation.valid,
        pdf_validation_status=validation.status,
        pdf_page_count=validation.page_count,
        pdf_title=validation.title,
    )
    db.add(file_object)
    db.flush()
    return file_object, False


def link_file_to_standard_resource(
    db: Session,
    *,
    task: models.OcrDownloadTask,
    file_object: models.FileObject,
    url_source: models.UrlSource,
    original_file_name: str,
) -> tuple[models.Document | None, models.DocumentVersion | None, str]:
    resource = db.get(models.StandardResource, task.resource_id) if task.resource_id else None
    trusted = db.get(models.TrustedSource, resource.source_id) if resource else None
    blocked, block_reason = should_block_batch2_formal_file_ingest(db, resource=resource, trusted_source=trusted)
    if blocked and resource is not None:
        record_batch2_file_evidence_only(
            db,
            resource=resource,
            url_source=url_source,
            file_hash=file_object.file_hash,
            summary=f"{original_file_name} size={file_object.file_size or 0}",
            reason=block_reason,
            trusted_source=trusted,
        )
        return None, None, "EVIDENCE_ONLY"

    if resource is not None and trusted is not None:
        admission = evaluate_batch2_file_admission(
            db,
            resource=resource,
            trusted_source=trusted,
            official_file_url=task.download_url or url_source.url,
            file_name=original_file_name,
            file_title=file_object.pdf_title,
        )
        if admission.evidence_only:
            record_batch2_file_evidence_only(
                db,
                resource=resource,
                url_source=url_source,
                file_hash=file_object.file_hash,
                summary=f"{original_file_name} size={file_object.file_size or 0}",
                reason=admission.reason,
                trusted_source=trusted,
            )
            return None, None, "EVIDENCE_ONLY"
        if not admission.allowed:
            return None, None, "NEED_REVIEW"

    document: models.Document | None = None

    if resource:
        matches = match_resource_to_documents(db, resource)
        if matches:
            document = db.get(models.Document, matches[0].document_id)

    if document is None and task.standard_no:
        normalized = normalize_standard_no(task.standard_no).normalized
        candidates = list(
            db.scalars(
                select(models.StandardResource).where(
                    or_(
                        models.StandardResource.normalized_standard_no == normalized,
                        models.StandardResource.standard_no == task.standard_no,
                    )
                )
            ).all()
        )
        if resource is None and candidates:
            resource = candidates[0]
            task.resource_id = resource.id
        if resource:
            for candidate in candidates:
                docs = match_resource_to_documents(db, candidate)
                if docs:
                    document = db.get(models.Document, docs[0].document_id)
                    resource = candidate
                    break

    name_similarity = _similarity(document.title if document else task.standard_name, task.standard_name or resource.standard_name if resource else "")
    if document and name_similarity < 60 and task.standard_no:
        upsert_pending_alert(
            db,
            alert_type="ocr_link_name_mismatch",
            alert_level=models.AlertLevel.high.value,
            risk_level="high",
            message=f"编号 {task.standard_no} 一致但名称相似度仅 {name_similarity}%，需人工监督",
            dedupe_key=f"ocr-link:{task.id}:{task.standard_no}",
            document_id=document.id,
        )
        return document, None, "NEED_REVIEW"

    if document is not None:
        existing_same_hash = db.scalars(
            select(models.DocumentVersion)
            .where(
                models.DocumentVersion.document_id == document.id,
                models.DocumentVersion.file_hash == file_object.file_hash,
            )
            .order_by(models.DocumentVersion.is_current.desc(), models.DocumentVersion.id.desc())
        ).first()
        if existing_same_hash is not None:
            preferred_path = file_object.local_path or file_object.storage_path or existing_same_hash.file_path
            if (
                preferred_path
                and existing_same_hash.file_path != preferred_path
                and existing_same_hash.file_path.startswith("url-sources/")
                and preferred_path.startswith("objects/sha256/")
            ):
                existing_same_hash.file_path = preferred_path
            if existing_same_hash.file_object_id is None:
                existing_same_hash.file_object_id = file_object.id
            if existing_same_hash.url_source_id is None:
                existing_same_hash.url_source_id = url_source.id
            db.query(models.DocumentVersion).filter(
                models.DocumentVersion.document_id == document.id,
                models.DocumentVersion.id != existing_same_hash.id,
            ).update({"is_current": False}, synchronize_session=False)
            existing_same_hash.is_current = True
            document.current_version_id = existing_same_hash.id
            if resource:
                match_resource_to_documents(db, resource)
            return document, existing_same_hash, "unchanged"

    if document is None:
        number_parts = normalize_standard_no(task.standard_no or resource.standard_no if resource else None)
        document = models.Document(
            title=(resource.standard_name if resource else None) or task.standard_name or original_file_name,
            standard_no=task.standard_no or (resource.standard_no if resource else None),
            raw_standard_no=number_parts.raw,
            normalized_standard_no=number_parts.normalized,
            standard_prefix=number_parts.prefix,
            standard_main_no=number_parts.main_no,
            standard_year=number_parts.year,
            standard_revision_note=number_parts.revision_note,
            doc_type=doc_type(original_file_name, "application/pdf"),
            valid_status=models.ValidStatus.pending.value,
            review_status=models.ReviewStatus.pending.value,
        )
        db.add(document)
        db.flush()
        change_type = models.ChangeType.created.value
    else:
        db.query(models.DocumentVersion).filter(
            models.DocumentVersion.document_id == document.id,
            models.DocumentVersion.is_current.is_(True),
        ).update({"is_current": False})
        change_type = models.ChangeType.updated.value

    version = models.DocumentVersion(
        document_id=document.id,
        url_source_id=url_source.id,
        version_no=f"v{len(document.versions) + 1}",
        file_name=original_file_name,
        original_file_name=original_file_name,
        file_path=file_object.local_path or file_object.storage_path or "",
        file_hash=file_object.file_hash,
        file_size=file_object.file_size,
        content_hash=file_object.content_hash,
        change_type=change_type,
        is_current=True,
        file_object_id=file_object.id,
    )
    db.add(version)
    db.flush()
    document.current_version_id = version.id

    if resource:
        match_resource_to_documents(db, resource)
        db.add(
            models.StandardEvidence(
                standard_resource_id=resource.id,
                document_id=document.id,
                source_name=resource.source_name,
                source_level="A",
                source_url=task.download_url,
                raw_status_text=resource.source_status,
                parsed_status="OCR归档",
                page_summary=f"OCR 受控下载归档 file_hash={file_object.file_hash}",
                page_html_hash=file_object.file_hash,
                evidence_note=f"ocr_task_id={task.id}",
            )
        )
    return document, version, "linked"


def _schedule_retry(task: models.OcrDownloadTask, db: Session, *, status: str, error: str) -> None:
    task.attempt_count += 1
    task.last_error = error[:2000]
    delay = get_int_setting(db, "ocr_retry_delay_seconds", default=300)
    if task.attempt_count >= task.max_attempts:
        task.status = TASK_NEED_MANUAL
        task.finished_at = datetime.now(UTC)
    else:
        task.next_retry_at = datetime.now(UTC) + timedelta(seconds=delay * task.attempt_count)
        task.status = TASK_PENDING
    task.locked_by = None
    task.locked_at = None


def run_ocr_download_task(db: Session, task_id: int, *, storage_root: Path | None = None) -> dict:
    if not get_bool_setting(db, "ocr_download_enabled", default=True):
        return {"ok": False, "message": "ocr_download_enabled=false"}

    task = db.get(models.OcrDownloadTask, task_id)
    if task is None:
        raise ValueError("task not found")
    if task.status != TASK_RUNNING:
        return {"ok": False, "message": f"task status={task.status}"}

    storage_root = storage_root or Path(get_settings().storage_root)
    url_source = db.get(models.UrlSource, task.url_source_id) if task.url_source_id else None
    if url_source is None and task.download_url:
        resource = db.get(models.StandardResource, task.resource_id) if task.resource_id else None
        if resource:
            url_source = create_or_get_ocr_url_source(db, resource, task.download_url)
            task.url_source_id = url_source.id

    if url_source is None:
        task.status = TASK_DOWNLOAD_FAILED
        task.last_error = "缺少 url_source"
        task.finished_at = datetime.now(UTC)
        db.commit()
        return {"ok": False, "status": task.status, "message": "缺少 url_source"}

    try:
        write_process_audit_log(
            db,
            step_name="run_ocr_download_task",
            target_type="ocr_download_task",
            target_id=task.id,
            source_id=task.source_id,
            result="started",
        )
        downloaded = submit_captcha_and_download(task, db)
        write_process_audit_log(
            db,
            step_name="submit_captcha_and_download",
            target_type="ocr_download_task",
            target_id=task.id,
            source_id=task.source_id,
            result="downloaded",
            output_summary=json.dumps({"bytes": len(downloaded.content)}, ensure_ascii=False),
        )

        validation = validate_pdf(downloaded.content, content_type=downloaded.content_type)
        if not validation.valid:
            task.status = TASK_PDF_INVALID
            task.last_error = validation.message
            task.finished_at = datetime.now(UTC)
            write_process_audit_log(
                db,
                step_name="validate_pdf",
                target_type="ocr_download_task",
                target_id=task.id,
                source_id=task.source_id,
                result="invalid",
                status="failed",
                error_message=validation.message,
            )
            upsert_pending_alert(
                db,
                alert_type="ocr_pdf_invalid",
                alert_level=models.AlertLevel.high.value,
                risk_level="high",
                message=f"{task.standard_no or '-'} {task.standard_name or ''}：{validation.message}",
                dedupe_key=f"ocr-pdf-invalid:{task.id}",
                document_id=None,
                url_source_id=url_source.id if url_source else None,
            )
            db.commit()
            return {"ok": False, "status": task.status, "message": validation.message}

        file_name = guess_file_name(downloaded.url, downloaded.content_type, downloaded.content_disposition)
        file_object, is_duplicate = archive_file_object(
            db,
            content=downloaded.content,
            file_name=file_name,
            content_type=downloaded.content_type,
            validation=validation,
            storage_root=storage_root,
        )
        task.file_object_id = file_object.id

        link_document, _version, link_status = link_file_to_standard_resource(
            db,
            task=task,
            file_object=file_object,
            url_source=url_source,
            original_file_name=file_name,
        )
        if link_status == "NEED_REVIEW":
            task.status = TASK_NEED_MANUAL
            task.finished_at = datetime.now(UTC)
            db.commit()
            return {"ok": False, "status": task.status, "message": "名称相似度过低，转人工"}
        if link_status == "EVIDENCE_ONLY":
            task.status = TASK_SKIPPED
            task.finished_at = datetime.now(UTC)
            task.last_error = "第二批源文件仅留证，不入正式库"
            db.commit()
            return {"ok": True, "status": task.status, "file_object_id": file_object.id, "message": task.last_error}
        if link_status == "unchanged":
            task.status = TASK_DUPLICATE_FILE
            task.finished_at = datetime.now(UTC)
            task.last_error = None
            db.commit()
            return {
                "ok": True,
                "status": task.status,
                "file_object_id": file_object.id,
                "message": "文件内容无变化，未创建新版本",
            }

        task.status = TASK_DUPLICATE_FILE if is_duplicate else TASK_ARCHIVED
        task.finished_at = datetime.now(UTC)
        task.last_error = None
        write_process_audit_log(
            db,
            step_name="archive_file_object",
            target_type="ocr_download_task",
            target_id=task.id,
            source_id=task.source_id,
            result=task.status,
            output_summary=json.dumps(
                {"file_object_id": file_object.id, "duplicate": is_duplicate},
                ensure_ascii=False,
            ),
        )
        db.commit()
        return {"ok": True, "status": task.status, "file_object_id": file_object.id}

    except (OpenstdCaptchaIncorrectError, SamrPortalCaptchaIncorrectError) as exc:
        _schedule_retry(task, db, status=TASK_CAPTCHA_FAILED, error=str(exc))
        write_process_audit_log(
            db,
            step_name="solve_captcha_by_ocr",
            target_type="ocr_download_task",
            target_id=task.id,
            source_id=task.source_id,
            result=task.status,
            status="failed",
            error_message=str(exc),
        )
        db.commit()
        return {"ok": False, "status": task.status, "message": str(exc)}
    except (OpenstdCaptchaError, SamrPortalCaptchaError) as exc:
        _schedule_retry(task, db, status=TASK_OCR_FAILED, error=str(exc))
        write_process_audit_log(
            db,
            step_name="ocr_download",
            target_type="ocr_download_task",
            target_id=task.id,
            source_id=task.source_id,
            result=task.status,
            status="failed",
            error_message=str(exc),
        )
        db.commit()
        return {"ok": False, "status": task.status, "message": str(exc)}
    except Exception as exc:
        _schedule_retry(task, db, status=TASK_DOWNLOAD_FAILED, error=str(exc))
        write_process_audit_log(
            db,
            step_name="run_ocr_download_task",
            target_type="ocr_download_task",
            target_id=task.id,
            source_id=task.source_id,
            result=task.status,
            status="failed",
            error_message=str(exc),
        )
        db.commit()
        return {"ok": False, "status": task.status, "message": str(exc)}
    finally:
        if task.locked_by or task.locked_at:
            task.locked_by = None
            task.locked_at = None
            db.commit()


def retry_ocr_task(db: Session, task_id: int) -> models.OcrDownloadTask:
    task = db.get(models.OcrDownloadTask, task_id)
    if task is None:
        raise ValueError("task not found")
    task.status = TASK_PENDING
    task.next_retry_at = None
    task.last_error = None
    task.finished_at = None
    task.locked_by = None
    task.locked_at = None
    write_process_audit_log(db, step_name="retry_ocr_task", target_type="ocr_download_task", target_id=task.id, result="pending")
    db.commit()
    db.refresh(task)
    return task


def skip_ocr_task(db: Session, task_id: int, *, reason: str | None = None) -> models.OcrDownloadTask:
    task = db.get(models.OcrDownloadTask, task_id)
    if task is None:
        raise ValueError("task not found")
    task.status = TASK_SKIPPED
    task.last_error = reason
    task.finished_at = datetime.now(UTC)
    write_process_audit_log(db, step_name="skip_ocr_task", target_type="ocr_download_task", target_id=task.id, result="skipped")
    db.commit()
    db.refresh(task)
    return task


def mark_ocr_task_need_manual(db: Session, task_id: int, *, reason: str | None = None) -> models.OcrDownloadTask:
    task = db.get(models.OcrDownloadTask, task_id)
    if task is None:
        raise ValueError("task not found")
    task.status = TASK_NEED_MANUAL
    task.last_error = reason
    task.finished_at = datetime.now(UTC)
    write_process_audit_log(db, step_name="mark_need_manual", target_type="ocr_download_task", target_id=task.id, result="need_manual")
    db.commit()
    db.refresh(task)
    return task


def ocr_task_dashboard(db: Session) -> dict:
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    pending = db.scalar(select(func.count()).select_from(models.OcrDownloadTask).where(models.OcrDownloadTask.status == TASK_PENDING)) or 0
    running = db.scalar(select(func.count()).select_from(models.OcrDownloadTask).where(models.OcrDownloadTask.status == TASK_RUNNING)) or 0
    success_today = db.scalar(
        select(func.count())
        .select_from(models.OcrDownloadTask)
        .where(models.OcrDownloadTask.status.in_((TASK_ARCHIVED, TASK_DUPLICATE_FILE)), models.OcrDownloadTask.finished_at >= today_start)
    ) or 0
    failed = db.scalar(
        select(func.count())
        .select_from(models.OcrDownloadTask)
        .where(
            models.OcrDownloadTask.status.in_(
                (TASK_OCR_FAILED, TASK_CAPTCHA_FAILED, TASK_DOWNLOAD_FAILED, TASK_PDF_INVALID)
            )
        )
    ) or 0
    need_manual = db.scalar(select(func.count()).select_from(models.OcrDownloadTask).where(models.OcrDownloadTask.status == TASK_NEED_MANUAL)) or 0
    attempts = db.scalar(select(func.sum(models.OcrDownloadTask.attempt_count)).select_from(models.OcrDownloadTask)) or 0
    archived = db.scalar(select(func.count()).select_from(models.OcrDownloadTask).where(models.OcrDownloadTask.status.in_((TASK_ARCHIVED, TASK_DUPLICATE_FILE)))) or 0
    pdf_valid = db.scalar(select(func.count()).select_from(models.FileObject).where(models.FileObject.pdf_valid.is_(True))) or 0
    pdf_total = db.scalar(select(func.count()).select_from(models.FileObject)) or 0
    ocr_success_rate = round((archived / attempts * 100), 1) if attempts else 0.0
    pdf_pass_rate = round((pdf_valid / pdf_total * 100), 1) if pdf_total else 0.0
    return {
        "pending": pending,
        "running": running,
        "success_today": success_today,
        "ocr_success_rate": ocr_success_rate,
        "pdf_pass_rate": pdf_pass_rate,
        "failed": failed,
        "need_manual": need_manual,
    }


def list_ocr_tasks_page(
    db: Session,
    *,
    cursor: int | None = None,
    page_size: int = 50,
    status: str | None = None,
    q: str | None = None,
) -> dict:
    page_size = max(1, min(page_size, 200))
    query = select(models.OcrDownloadTask).order_by(models.OcrDownloadTask.id.desc())
    if cursor:
        query = query.where(models.OcrDownloadTask.id < cursor)
    if status:
        query = query.where(models.OcrDownloadTask.status == status)
    if q:
        keyword = f"%{q.strip()}%"
        query = query.where(
            or_(
                models.OcrDownloadTask.standard_no.like(keyword),
                models.OcrDownloadTask.standard_name.like(keyword),
                models.OcrDownloadTask.last_error.like(keyword),
            )
        )
    rows = db.scalars(query.limit(page_size + 1)).all()
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    total = db.scalar(select(func.count()).select_from(models.OcrDownloadTask)) or 0
    return {
        "total": total,
        "items": rows,
        "next_cursor": rows[-1].id if has_more and rows else None,
        "has_more": has_more,
    }


def list_file_objects_page(
    db: Session,
    *,
    cursor: int | None = None,
    page_size: int = 50,
    q: str | None = None,
    pdf_valid: bool | None = None,
    filter_type: str | None = None,
) -> dict:
    page_size = max(1, min(page_size, 200))
    query = select(models.FileObject).order_by(models.FileObject.id.desc())
    if cursor:
        query = query.where(models.FileObject.id < cursor)
    if q:
        keyword = f"%{q.strip()}%"
        query = query.where(or_(models.FileObject.file_hash.like(keyword), models.FileObject.pdf_title.like(keyword)))
    if pdf_valid is not None:
        query = query.where(models.FileObject.pdf_valid.is_(pdf_valid))
    if filter_type == "large":
        query = query.where(models.FileObject.file_size >= 20 * 1024 * 1024)
    elif filter_type == "unlinked":
        linked_ids = select(models.DocumentVersion.file_object_id).where(models.DocumentVersion.file_object_id.is_not(None))
        query = query.where(~models.FileObject.id.in_(linked_ids))
    elif filter_type == "multi_source":
        pass
    rows = db.scalars(query.limit(page_size + 1)).all()
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    total = db.scalar(select(func.count()).select_from(models.FileObject)) or 0

    items = []
    for row in rows:
        linked_standards = db.scalar(
            select(func.count(func.distinct(models.StandardFileMatch.standard_resource_id)))
            .select_from(models.DocumentVersion)
            .join(models.StandardFileMatch, models.StandardFileMatch.document_version_id == models.DocumentVersion.id)
            .where(models.DocumentVersion.file_object_id == row.id)
        ) or db.scalar(
            select(func.count(func.distinct(models.StandardFileMatch.standard_resource_id)))
            .select_from(models.DocumentVersion)
            .join(models.StandardFileMatch, models.StandardFileMatch.document_id == models.DocumentVersion.document_id)
            .where(models.DocumentVersion.file_object_id == row.id)
        ) or 0
        linked_sources = db.scalar(
            select(func.count(func.distinct(models.DocumentVersion.url_source_id)))
            .select_from(models.DocumentVersion)
            .where(models.DocumentVersion.file_object_id == row.id, models.DocumentVersion.url_source_id.is_not(None))
        ) or 0
        items.append(
            {
                "id": row.id,
                "file_hash": row.file_hash,
                "file_size": row.file_size,
                "pdf_valid": row.pdf_valid,
                "pdf_validation_status": row.pdf_validation_status,
                "pdf_page_count": row.pdf_page_count,
                "storage_backend": row.storage_backend,
                "storage_path": row.storage_path,
                "local_path": row.local_path,
                "linked_standard_count": linked_standards,
                "linked_source_count": linked_sources,
                "created_at": row.created_at,
            }
        )
    return {
        "total": total,
        "items": items,
        "next_cursor": rows[-1].id if has_more and rows else None,
        "has_more": has_more,
    }


def get_file_object_detail(db: Session, file_object_id: int) -> dict | None:
    row = db.get(models.FileObject, file_object_id)
    if row is None:
        return None
    linked_standards = db.scalar(
        select(func.count(func.distinct(models.StandardFileMatch.standard_resource_id)))
        .select_from(models.DocumentVersion)
        .join(models.StandardFileMatch, models.StandardFileMatch.document_id == models.DocumentVersion.document_id)
        .where(models.DocumentVersion.file_object_id == row.id)
    ) or 0
    linked_sources = db.scalar(
        select(func.count(func.distinct(models.DocumentVersion.url_source_id)))
        .select_from(models.DocumentVersion)
        .where(models.DocumentVersion.file_object_id == row.id, models.DocumentVersion.url_source_id.is_not(None))
    ) or 0
    return {
        "id": row.id,
        "file_hash": row.file_hash,
        "file_size": row.file_size,
        "pdf_valid": row.pdf_valid,
        "pdf_validation_status": row.pdf_validation_status,
        "pdf_page_count": row.pdf_page_count,
        "pdf_title": row.pdf_title,
        "storage_backend": row.storage_backend,
        "storage_path": row.storage_path,
        "local_path": row.local_path,
        "baidu_pan_uri": row.baidu_pan_uri,
        "linked_standard_count": linked_standards,
        "linked_source_count": linked_sources,
        "created_at": row.created_at,
    }
