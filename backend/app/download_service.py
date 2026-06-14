from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.alerts import create_operational_alert
from app.governance_automation import auto_resolve_ingest_success_alerts
from app.governance_service import log_process_audit
from app.baidu_pan_storage import BaiduPanClient, BaiduPanError, append_baidu_pan_sync_remark, build_baidu_pan_sync_payload, load_baidu_pan_config
from app.classification_decisions import DECISION_DUPLICATE_EXISTING
from app.document_classification_service import (
    apply_classification_to_document_fields,
    apply_fields_to_document,
    can_link_classification_to_existing_document,
    classify_document_file,
    is_isolated_classification_decision,
    record_classification_evidence,
)
from app.standard_number import normalize_standard_no
from app.storage import check_storage_root, relative_storage_path
from app.settings_store import get_setting


DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 30
DEFAULT_DOWNLOAD_RETRIES = int(os.getenv("DOWNLOAD_RETRIES", "3"))
CHECK_LOG_SUCCESS_MIN_INTERVAL_HOURS = float(os.getenv("CHECK_LOG_SUCCESS_MIN_INTERVAL_HOURS", "24"))


@dataclass
class DownloadedContent:
    status_code: int
    url: str
    content: bytes
    content_type: str | None = None
    content_disposition: str | None = None


@dataclass
class DownloadFailure:
    status_code: int | None
    message: str
    alert_type: str = "下载失败"


def safe_archive_file_stem(value: str, *, fallback: str = "document") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\r\n\t]+', " ", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-_")
    return cleaned or fallback


def archive_content_disposition(file_stem: str, *, suffix: str = ".pdf") -> str:
    safe_stem = safe_archive_file_stem(file_stem, fallback="document")
    return f'attachment; filename="{safe_stem}{suffix}"'


def guess_file_name(url: str, content_type: str | None, content_disposition: str | None) -> str:
    if content_disposition:
        match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition, flags=re.I)
        if match:
            return Path(unquote(match.group(1))).name

    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name.replace("+", " ")
    if name and "." in name:
        return name

    if content_type and "html" in content_type:
        return "page.html"
    if content_type and "pdf" in content_type:
        return "document.pdf"
    if content_type and "word" in content_type:
        return "document.docx"
    if content_type and "excel" in content_type:
        return "document.xlsx"
    return "download.bin"


def doc_type(file_name: str, content_type: str | None) -> str:
    suffix = Path(file_name).suffix.lower().lstrip(".")
    if suffix:
        return suffix.upper()
    if content_type and "html" in content_type:
        return "HTML"
    return "BIN"


def extract_standard_no(source: models.UrlSource) -> str | None:
    text = source.remark or ""
    for pattern in (
        r"standard_no\s*=\s*([^；;\r\n]+)",
        r"编号[:：]\s*([^；;\r\n]+)",
    ):
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(1).strip() or None
    return None


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_archive_file(storage_root: Path, source_id: int, file_name: str, content: bytes) -> Path:
    relative_path = archive_relative_path(source_id, file_name)
    target_path = storage_root / relative_path
    target_dir = target_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(content)
    return target_path


def archive_relative_path(source_id: int, file_name: str) -> str:
    now = datetime.now(UTC)
    return f"url-sources/{source_id}/{now.strftime('%Y%m%d')}/{now.strftime('%H%M%S')}_{Path(file_name).name}"


def archive_object_relative_path(file_hash: str, file_name: str) -> str:
    suffix = Path(file_name).suffix.lower() or ".bin"
    return f"objects/sha256/{file_hash[:2]}/{file_hash[2:4]}/{file_hash}{suffix}"


def configured_storage_backend(db: Session) -> str:
    backend = (os.getenv("STORAGE_BACKEND") or get_setting(db, "storage_backend", "local") or "local").strip().lower()
    return backend if backend in {"local", "baidu_pan", "dual"} else "local"


def create_alert(
    db: Session,
    source: models.UrlSource,
    alert_type: str,
    message: str,
    level: str = models.AlertLevel.medium.value,
    document_id: int | None = None,
) -> models.Alert | None:
    high_risk = level == models.AlertLevel.high.value
    alert = create_operational_alert(
        db,
        source=source,
        alert_type=alert_type,
        message=message,
        level=level,
        document_id=document_id,
        risk_level="high" if high_risk else "medium",
        high_risk=high_risk,
    )
    if alert is None:
        log_process_audit(
            db,
            process_name="url_check",
            action="alert_suppressed",
            target_type="url_source",
            target_id=source.id,
            message=message,
            detail={"alert_type": alert_type, "level": level, "high_risk": high_risk},
        )
    return alert


def log_check(
    db: Session,
    source: models.UrlSource,
    status_code: int | None,
    result: str,
    message: str,
) -> None:
    now = datetime.now(UTC)
    change_detected = result in {models.ChangeType.created.value, models.ChangeType.updated.value}
    low_value_success = not change_detected and status_code is not None and status_code < 400
    if low_value_success and CHECK_LOG_SUCCESS_MIN_INTERVAL_HOURS > 0:
        cutoff = now - timedelta(hours=CHECK_LOG_SUCCESS_MIN_INTERVAL_HOURS)
        recent_same_result = db.scalars(
            select(models.CheckLog.id)
            .where(models.CheckLog.url_source_id == source.id)
            .where(models.CheckLog.result == result)
            .where(models.CheckLog.status_code == status_code)
            .where(models.CheckLog.error_message.is_(None))
            .where(models.CheckLog.created_at >= cutoff)
            .limit(1)
        ).first()
        if recent_same_result is not None:
            source.last_checked_at = now
            return
    db.add(
        models.CheckLog(
            url_source_id=source.id,
            check_time=now,
            status_code=status_code,
            result=result,
            change_detected=change_detected,
            error_message=message if result == "失败" else None,
            message=message,
        )
    )
    source.last_checked_at = now


def resolve_source_failure_alerts(db: Session, source: models.UrlSource) -> None:
    db.query(models.Alert).filter(
        models.Alert.url_source_id == source.id,
        models.Alert.status == models.AlertStatus.pending.value,
        models.Alert.alert_type.in_(["下载失败", "链接失效", "存储目录不可用"]),
    ).update(
        {
            "status": models.AlertStatus.handled.value,
            "handled_at": datetime.now(UTC),
            "handled_by": "system-auto-retry",
        },
        synchronize_session=False,
    )


def fetch_url(
    source: models.UrlSource,
    timeout_seconds: int = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    retries: int = DEFAULT_DOWNLOAD_RETRIES,
) -> DownloadedContent | DownloadFailure:
    last_error: str | None = None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StandardDocsIngest/1.0",
        "Accept": "*/*",
    }
    response = None
    for attempt in range(1, retries + 1):
        try:
            with httpx.Client(follow_redirects=True, timeout=timeout_seconds, headers=headers) as client:
                response = client.get(source.url)
        except httpx.HTTPError as exc:
            last_error = f"访问失败：{exc}"
            if attempt < retries:
                time.sleep(min(2 * attempt, 10))
                continue
            return DownloadFailure(None, f"{last_error}；已重试 {retries} 次")

        if response.status_code in {408, 429, 500, 502, 503, 504} and attempt < retries:
            last_error = f"URL 返回临时状态码 {response.status_code}"
            time.sleep(min(2 * attempt, 10))
            continue
        break

    if response is None:
        return DownloadFailure(None, last_error or "访问失败")

    if response.status_code >= 400:
        return DownloadFailure(response.status_code, f"URL 返回状态码 {response.status_code}", "链接失效")

    return DownloadedContent(
        status_code=response.status_code,
        url=str(response.url),
        content=response.content,
        content_type=response.headers.get("content-type"),
        content_disposition=response.headers.get("content-disposition"),
    )


def record_download_failure(db: Session, source: models.UrlSource, failure: DownloadFailure) -> schemas.UrlCheckResult:
    source.status = models.SourceStatus.invalid.value if failure.status_code == 404 else models.SourceStatus.error.value
    source.error_message = failure.message
    alert = create_alert(db, source, failure.alert_type, failure.message, models.AlertLevel.high.value)
    log_check(db, source, failure.status_code, "失败", failure.message)
    db.commit()
    return schemas.UrlCheckResult(
        source_id=source.id,
        url=source.url,
        ok=False,
        status_code=failure.status_code,
        result="失败",
        message=failure.message,
        alert_id=alert.id if alert else None,
    )


def archive_downloaded_content(
    db: Session,
    source: models.UrlSource,
    storage_root: Path,
    downloaded: DownloadedContent,
    *,
    defer_baidu_upload: bool = False,
) -> schemas.UrlCheckResult:
    from app.batch2_admission import (
        evaluate_batch2_file_admission,
        record_batch2_file_evidence_only,
        should_block_batch2_formal_file_ingest,
    )
    from app.settings_store import get_bool_setting
    from app.status_calibration import extract_standard_resource_id_from_remark

    if not get_bool_setting(db, "ingest_enabled", default=False):
        return record_download_failure(
            db,
            source,
            DownloadFailure(
                None,
                "文件入库已暂停：当前处于数据治理阶段，请完成来源画像后再开启 ingest_enabled。",
                "入库暂停",
            ),
        )

    storage_backend = configured_storage_backend(db)
    needs_local_storage = storage_backend in {"local", "dual"}
    storage_status = check_storage_root(db, storage_root) if needs_local_storage else None
    if storage_status and not storage_status.available and storage_status.pause_download_if_unavailable:
        return record_download_failure(
            db,
            source,
            DownloadFailure(None, f"存储目录不可用，已暂停下载：{storage_status.message}；目录：{storage_status.root}", "存储目录不可用"),
        )

    file_hash = sha256_bytes(downloaded.content)
    file_name = guess_file_name(downloaded.url, downloaded.content_type, downloaded.content_disposition)

    classification = classify_document_file(
        db,
        file_name=file_name,
        file_hash=file_hash,
        source=source,
        content_type=downloaded.content_type,
        source_name=source.source_name,
        source_category=source.category,
        allow_external_search=False,
    )

    if classification.decision == DECISION_DUPLICATE_EXISTING and classification.matched_version_id:
        version = db.get(models.DocumentVersion, classification.matched_version_id)
        if version:
            message = classification.decision_reason or "内容无变化"
            record_classification_evidence(
                db,
                document=version.document,
                classification=classification,
                source=source,
                file_hash=file_hash,
            )
            log_check(db, source, downloaded.status_code, "无变化", message)
            db.commit()
            return schemas.UrlCheckResult(
                source_id=source.id,
                url=source.url,
                ok=True,
                status_code=downloaded.status_code,
                result="无变化",
                message=message,
                document_id=version.document_id,
                version_id=version.id,
                file_hash=file_hash,
                change_type=models.ChangeType.unchanged.value,
            )

    linked_resource: models.StandardResource | None = None
    resource_id = extract_standard_resource_id_from_remark(source.remark)
    if resource_id:
        linked_resource = db.get(models.StandardResource, resource_id)
    if linked_resource is not None:
        blocked, block_reason = should_block_batch2_formal_file_ingest(db, resource=linked_resource)
        if blocked:
            record_batch2_file_evidence_only(
                db,
                resource=linked_resource,
                url_source=source,
                file_hash=file_hash,
                summary=f"{file_name} size={len(downloaded.content)}",
                reason=block_reason,
            )
            log_check(db, source, downloaded.status_code, "跳过", f"第二批源仅留证：{block_reason}")
            db.commit()
            return schemas.UrlCheckResult(
                source_id=source.id,
                url=source.url,
                ok=True,
                status_code=downloaded.status_code,
                result="跳过",
                message=f"第二批源文件仅留证，不入正式库：{block_reason}",
                file_hash=file_hash,
                change_type=models.ChangeType.unchanged.value,
            )
        admission = evaluate_batch2_file_admission(
            db,
            resource=linked_resource,
            official_file_url=source.url,
            file_name=file_name,
        )
        if admission.evidence_only:
            record_batch2_file_evidence_only(
                db,
                resource=linked_resource,
                url_source=source,
                file_hash=file_hash,
                summary=f"{file_name} size={len(downloaded.content)}",
                reason=admission.reason,
            )
            log_check(db, source, downloaded.status_code, "跳过", f"第二批源仅留证：{admission.reason}")
            db.commit()
            return schemas.UrlCheckResult(
                source_id=source.id,
                url=source.url,
                ok=True,
                status_code=downloaded.status_code,
                result="跳过",
                message=f"第二批源文件仅留证，不入正式库：{admission.reason}",
                file_hash=file_hash,
                change_type=models.ChangeType.unchanged.value,
            )

    latest = db.scalars(
        select(models.DocumentVersion)
        .where(models.DocumentVersion.url_source_id == source.id, models.DocumentVersion.is_current.is_(True))
        .order_by(desc(models.DocumentVersion.downloaded_at), desc(models.DocumentVersion.id))
    ).first()

    source.status = models.SourceStatus.normal.value
    source.error_message = None
    resolve_source_failure_alerts(db, source)

    if latest and latest.file_hash == file_hash:
        message = "内容无变化"
        log_check(db, source, downloaded.status_code, "无变化", message)
        db.commit()
        return schemas.UrlCheckResult(
            source_id=source.id,
            url=source.url,
            ok=True,
            status_code=downloaded.status_code,
            result="无变化",
            message=message,
            document_id=latest.document_id,
            version_id=latest.id,
            file_hash=file_hash,
            change_type=models.ChangeType.unchanged.value,
        )

    existing_for_source = db.scalars(
        select(models.DocumentVersion)
        .where(models.DocumentVersion.url_source_id == source.id, models.DocumentVersion.file_hash == file_hash)
        .order_by(models.DocumentVersion.id)
    ).first()
    if existing_for_source:
        existing_for_source.is_current = True
        db.query(models.DocumentVersion).filter(
            models.DocumentVersion.url_source_id == source.id,
            models.DocumentVersion.id != existing_for_source.id,
        ).update({"is_current": False})
        message = "同一来源已归档相同文件，跳过重复写入"
        log_check(db, source, downloaded.status_code, "无变化", message)
        db.commit()
        return schemas.UrlCheckResult(
            source_id=source.id,
            url=source.url,
            ok=True,
            status_code=downloaded.status_code,
            result="无变化",
            message=message,
            document_id=existing_for_source.document_id,
            version_id=existing_for_source.id,
            file_hash=file_hash,
            change_type=models.ChangeType.unchanged.value,
        )

    document: models.Document | None = None
    doc_fields = apply_classification_to_document_fields(classification)
    isolated = is_isolated_classification_decision(classification.decision)

    if not isolated and latest:
        document = latest.document
        latest.is_current = False
        change_type = models.ChangeType.updated.value
        alert_type = "文件更新"
        message = f"发现新版本：{file_name}"
    elif not isolated and can_link_classification_to_existing_document(classification):
        document = db.get(models.Document, classification.matched_document_id)
        if document is not None:
            change_type = models.ChangeType.updated.value
            alert_type = "文件更新"
            message = f"关联已有标准新版本：{file_name}"

    if document is None:
        document = models.Document(
            **doc_fields,
            doc_type=doc_type(file_name, downloaded.content_type),
        )
        db.add(document)
        db.flush()
        change_type = models.ChangeType.created.value
        alert_type = "冲突隔离" if isolated else "新增文件"
        message = (
            f"隔离归档：{file_name}"
            if isolated
            else f"首次归档：{file_name}"
        )
    else:
        apply_fields_to_document(document, doc_fields)

    relative_path = archive_relative_path(source.id, file_name)
    storage_path = ""
    queued_baidu_upload = False
    baidu_sync_payload: dict | None = None
    if storage_backend in {"baidu_pan", "dual"}:
        if defer_baidu_upload:
            queued_baidu_upload = True
        else:
            try:
                remote_relative_path = archive_object_relative_path(file_hash, file_name)
                remote_result = BaiduPanClient(load_baidu_pan_config(db)).upload_bytes(downloaded.content, remote_relative_path)
                baidu_sync_payload = build_baidu_pan_sync_payload(
                    remote_result=remote_result,
                    file_hash=file_hash,
                    source="inline_upload",
                )
                if storage_backend == "baidu_pan":
                    storage_path = remote_result.uri
            except BaiduPanError as exc:
                return record_download_failure(db, source, DownloadFailure(None, f"百度网盘归档失败：{exc}", "远端存储失败"))

    if needs_local_storage:
        if storage_status is None or not storage_status.available:
            return record_download_failure(
                db,
                source,
                DownloadFailure(None, "本地存储不可用，无法归档文件", "存储目录不可用"),
            )
        target_path = write_archive_file(storage_status.root, source.id, file_name, downloaded.content)
        storage_path = relative_storage_path(storage_status.root, target_path)

    version_count = len(document.versions) + 1
    version = models.DocumentVersion(
        document_id=document.id,
        url_source_id=source.id,
        version_no=f"v{version_count}",
        file_name=file_name,
        file_path=storage_path,
        file_hash=file_hash,
        file_size=len(downloaded.content),
        content_hash=file_hash,
        change_type=change_type,
        is_current=True,
        remark=append_baidu_pan_sync_remark(None, baidu_sync_payload) if baidu_sync_payload else None,
    )
    db.add(version)
    db.flush()
    document.current_version_id = version.id
    record_classification_evidence(
        db,
        document=document,
        classification=classification,
        source=source,
        file_hash=file_hash,
        resource_id=classification.matched_resource_id,
    )

    if classification.risk_level == "high" or classification.decision == "conflict_block":
        alert_level = models.AlertLevel.high.value
    elif classification.decision == "quarantine":
        alert_level = models.AlertLevel.medium.value
    else:
        alert_level = models.AlertLevel.high.value if change_type == models.ChangeType.updated.value else models.AlertLevel.medium.value
    alert = create_alert(db, source, alert_type, message, alert_level, document.id)
    log_check(db, source, downloaded.status_code, change_type, message)
    from app.status_calibration import link_archived_document_to_resources

    if not isolated:
        link_archived_document_to_resources(db, document=document, source=source)
    auto_resolve_ingest_success_alerts(
        db,
        document=document,
        source=source,
        change_type=change_type,
    )
    db.commit()
    db.refresh(version)
    if queued_baidu_upload:
        from app.baidu_upload_queue import get_baidu_upload_queue

        get_baidu_upload_queue().submit(
            version_id=version.id,
            file_hash=file_hash,
            file_name=file_name,
            content=downloaded.content,
        )
    if alert is not None:
        db.refresh(alert)

    return schemas.UrlCheckResult(
        source_id=source.id,
        url=source.url,
        ok=True,
        status_code=downloaded.status_code,
        result=change_type,
        message=message,
        document_id=document.id,
        version_id=version.id,
        alert_id=alert.id if alert else None,
        file_hash=file_hash,
        change_type=change_type,
    )


def check_url_source(
    db: Session,
    source: models.UrlSource,
    storage_root: Path,
    timeout_seconds: int = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
) -> schemas.UrlCheckResult:
    storage_backend = configured_storage_backend(db)
    storage_status = check_storage_root(db, storage_root) if storage_backend in {"local", "dual"} else None
    if storage_status and not storage_status.available and storage_status.pause_download_if_unavailable:
        return record_download_failure(
            db,
            source,
            DownloadFailure(None, f"存储目录不可用，已暂停下载：{storage_status.message}；目录：{storage_status.root}", "存储目录不可用"),
        )

    downloaded = fetch_url(source, timeout_seconds)
    if isinstance(downloaded, DownloadFailure):
        return record_download_failure(db, source, downloaded)
    return archive_downloaded_content(db, source, storage_status.root, downloaded)
