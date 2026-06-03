from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.alerts import mark_alert_auto_handled
from app.standard_number import normalize_standard_no
from app.storage import check_storage_root, relative_storage_path


DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 30
DEFAULT_DOWNLOAD_RETRIES = int(os.getenv("DOWNLOAD_RETRIES", "3"))


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


def guess_file_name(url: str, content_type: str | None, content_disposition: str | None) -> str:
    if content_disposition:
        match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition, flags=re.I)
        if match:
            return Path(unquote(match.group(1))).name

    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name
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
    now = datetime.now(UTC)
    target_dir = storage_root / "url-sources" / str(source_id) / now.strftime("%Y%m%d")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{now.strftime('%H%M%S')}_{Path(file_name).name}"
    target_path.write_bytes(content)
    return target_path


def create_alert(
    db: Session,
    source: models.UrlSource,
    alert_type: str,
    message: str,
    level: str = models.AlertLevel.medium.value,
    document_id: int | None = None,
) -> models.Alert:
    alert = models.Alert(
        document_id=document_id,
        url_source_id=source.id,
        alert_type=alert_type,
        alert_level=level,
        message=message,
    )
    mark_alert_auto_handled(alert)
    db.add(alert)
    db.flush()
    return alert


def log_check(
    db: Session,
    source: models.UrlSource,
    status_code: int | None,
    result: str,
    message: str,
) -> None:
    db.add(
        models.CheckLog(
            url_source_id=source.id,
            check_time=datetime.now(UTC),
            status_code=status_code,
            result=result,
            change_detected=result in {models.ChangeType.created.value, models.ChangeType.updated.value},
            error_message=message if result == "失败" else None,
            message=message,
        )
    )
    source.last_checked_at = datetime.now(UTC)


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
        alert_id=alert.id,
    )


def archive_downloaded_content(
    db: Session,
    source: models.UrlSource,
    storage_root: Path,
    downloaded: DownloadedContent,
) -> schemas.UrlCheckResult:
    storage_status = check_storage_root(db, storage_root)
    if not storage_status.available and storage_status.pause_download_if_unavailable:
        return record_download_failure(
            db,
            source,
            DownloadFailure(None, f"存储目录不可用，已暂停下载：{storage_status.message}；目录：{storage_status.root}", "存储目录不可用"),
        )

    file_hash = sha256_bytes(downloaded.content)
    file_name = guess_file_name(downloaded.url, downloaded.content_type, downloaded.content_disposition)

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

    if latest:
        document = latest.document
        latest.is_current = False
        change_type = models.ChangeType.updated.value
        alert_type = "文件更新"
        message = f"发现新版本：{file_name}"
    else:
        standard_no = extract_standard_no(source)
        number_parts = normalize_standard_no(standard_no)
        document = models.Document(
            title=source.source_name or Path(file_name).stem or source.url,
            standard_no=standard_no,
            raw_standard_no=number_parts.raw,
            normalized_standard_no=number_parts.normalized,
            standard_prefix=number_parts.prefix,
            standard_main_no=number_parts.main_no,
            standard_year=number_parts.year,
            standard_revision_note=number_parts.revision_note,
            doc_type=doc_type(file_name, downloaded.content_type),
            category=source.category,
            valid_status=models.ValidStatus.pending.value,
            review_status=models.ReviewStatus.pending.value,
        )
        db.add(document)
        db.flush()
        change_type = models.ChangeType.created.value
        alert_type = "新增文件"
        message = f"首次归档：{file_name}"

    target_path = write_archive_file(storage_status.root, source.id, file_name, downloaded.content)
    version_count = len(document.versions) + 1
    version = models.DocumentVersion(
        document_id=document.id,
        url_source_id=source.id,
        version_no=f"v{version_count}",
        file_name=file_name,
        file_path=relative_storage_path(storage_status.root, target_path),
        file_hash=file_hash,
        file_size=len(downloaded.content),
        content_hash=file_hash,
        change_type=change_type,
        is_current=True,
    )
    db.add(version)
    db.flush()
    document.current_version_id = version.id
    db.add(
        models.StandardEvidence(
            document_id=document.id,
            source_name=source.source_name or source.source_unit or "URL来源",
            source_level="file",
            source_url=source.url,
            raw_status_text=change_type,
            parsed_status=change_type,
            page_summary=f"{file_name} size={len(downloaded.content)} sha256={file_hash}",
            page_html_hash=file_hash,
            evidence_note=f"文件采集归档：{message}",
        )
    )

    alert_level = models.AlertLevel.high.value if change_type == models.ChangeType.updated.value else models.AlertLevel.medium.value
    alert = create_alert(db, source, alert_type, message, alert_level, document.id)
    log_check(db, source, downloaded.status_code, change_type, message)
    db.commit()
    db.refresh(version)
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
        alert_id=alert.id,
        file_hash=file_hash,
        change_type=change_type,
    )


def check_url_source(
    db: Session,
    source: models.UrlSource,
    storage_root: Path,
    timeout_seconds: int = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
) -> schemas.UrlCheckResult:
    storage_status = check_storage_root(db, storage_root)
    if not storage_status.available and storage_status.pause_download_if_unavailable:
        return record_download_failure(
            db,
            source,
            DownloadFailure(None, f"存储目录不可用，已暂停下载：{storage_status.message}；目录：{storage_status.root}", "存储目录不可用"),
        )

    downloaded = fetch_url(source, timeout_seconds)
    if isinstance(downloaded, DownloadFailure):
        return record_download_failure(db, source, downloaded)
    return archive_downloaded_content(db, source, storage_status.root, downloaded)
