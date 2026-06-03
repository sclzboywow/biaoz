import base64
import asyncio
import mimetypes
import re
import secrets
import string
import time
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.alerts import auto_handle_pending_alerts
from app.collection_tasks import normalize_collection_batch_size, run_url_check_task, stream_url_source_ids
from app.config import get_settings
from app.database import SessionLocal, get_db
from app.download_service import DownloadedContent, archive_downloaded_content
from app.guobiao_discovery import sync_discovered_sublibs
from app.guobiao_sync import sync_guobiao_resources  # noqa: F401  # imports and registers guobiao adapter
from app.samr_std_sync import _download_url, _online_url, sync_samr_std_resources  # noqa: F401  # imports and registers samr adapter
from app.scheduler import run_url_check_loop
from app.settings_store import (
    ensure_default_settings,
    ensure_default_trusted_sources,
    get_bool_setting,
    get_int_setting,
    get_setting,
)
from app.standard_number import normalize_standard_no
from app.status_calibration import calibrate_resource_status
from app.trusted_source_adapters import TrustedSourceSyncOptions, registry
from app.storage import check_storage_root, configured_storage_root, relative_storage_path, save_upload
from app.url_checker import check_url_source

settings = get_settings()

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    with SessionLocal() as db:
        ensure_default_settings(db)
        ensure_default_trusted_sources(db)
        auto_handle_pending_alerts(db)
        check_storage_root(db, settings.storage_root)
    app.state.url_check_task = asyncio.create_task(
        run_url_check_loop(
            settings.url_check_interval_seconds,
            settings.storage_root,
            settings.url_check_on_startup,
        )
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    task = getattr(app.state, "url_check_task", None)
    if task:
        task.cancel()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "system": settings.app_name}


api = FastAPI()

CAPTCHA_CHALLENGE_TTL_SECONDS = 600
GB688_BASE_URL = "http://c.gb688.cn/bzgk/gb"


def captcha_challenges() -> dict[str, dict]:
    store = getattr(app.state, "download_captcha_challenges", None)
    if store is None:
        store = {}
        app.state.download_captcha_challenges = store
    now = datetime.now(UTC)
    expired = [key for key, value in store.items() if value.get("expires_at", now) < now]
    for key in expired:
        store.pop(key, None)
    return store


def extract_hcno(resource: models.StandardResource) -> str | None:
    text = "\n".join(value for value in [resource.pdf_trial_url, resource.summary, resource.detail_url] if value)
    match = re.search(r"hcno=([A-Za-z0-9]+)", text)
    if match:
        return match.group(1)
    return None


def create_or_get_download_url_source(db: Session, resource: models.StandardResource, url: str) -> models.UrlSource:
    source = db.scalars(select(models.UrlSource).where(models.UrlSource.url == url)).first()
    if source:
        return source
    source = models.UrlSource(
        url=url,
        source_name=resource.standard_name or resource.standard_no or url,
        source_unit=resource.source_name,
        source_type="官方标准PDF",
        category="国家标准",
        check_frequency="manual",
        status=models.SourceStatus.normal.value,
        remark=f"standard_no={resource.standard_no or ''}; standard_resource_id={resource.id}; captcha=manual",
    )
    db.add(source)
    db.flush()
    return source


def apply_standard_number_fields(target, value: str | None) -> None:
    parts = normalize_standard_no(value)
    target.raw_standard_no = parts.raw
    target.normalized_standard_no = parts.normalized
    target.standard_prefix = parts.prefix
    target.standard_main_no = parts.main_no
    target.standard_year = parts.year
    target.standard_revision_note = parts.revision_note


def chain_processing_advice(
    source_status: str | None,
    system_status: str | None,
    manual_status: str | None,
    match_count: int,
    alert_count: int,
) -> str:
    if manual_status and manual_status not in {"待复核", "寰呭鏍?"}:
        return f"已存在人工复核结论：{manual_status}。后续以人工结论为准，可信源变化作为提醒。"
    if source_status and ("废止" in source_status or "搴熸" in source_status):
        return "可信源显示废止，建议复核是否需要标记为确认废止，并检查是否存在替代标准。"
    if system_status and "冲突" in system_status:
        return "系统发现多来源或状态冲突，建议优先查看证据链和同步记录。"
    if match_count == 0:
        return "尚未匹配本地文件，建议先按规范化编号匹配或人工确认。"
    if alert_count > 0:
        return "存在未处理提醒，建议查看提醒记录并完成处理。"
    if source_status and ("现行" in source_status or "鐜拌" in source_status):
        return "可信源显示现行，当前无明显异常，建议保持定期同步。"
    return "状态证据不足，建议补充可信源详情或人工复核。"

def cursor_window(db: Session, statement, id_column, page_size: int, cursor: int | None):
    limit = min(max(page_size, 1), 200)
    if cursor:
        statement = statement.where(id_column < cursor)
    rows = list(db.scalars(statement.order_by(desc(id_column)).limit(limit + 1)))
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = items[-1].id if has_more and items else None
    return items, next_cursor, has_more


@api.get("/url-sources", response_model=list[schemas.UrlSourceOut])
def list_url_sources(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    return crud.list_items(db, models.UrlSource, skip, limit)


@api.get("/url-sources/page", response_model=schemas.UrlSourcePage)
def page_url_sources(
    page: int = 1,
    page_size: int = 50,
    cursor: int | None = None,
    q: str | None = None,
    status: str | None = None,
    source_type: str | None = None,
    check_frequency: str | None = None,
    db: Session = Depends(get_db),
):
    page_size = min(max(page_size, 1), 200)
    statement = select(models.UrlSource)
    count_statement = select(func.count(models.UrlSource.id))
    filters = []
    if q:
        keyword = f"%{q}%"
        filters.append(
            or_(
                models.UrlSource.url.like(keyword),
                models.UrlSource.source_name.like(keyword),
                models.UrlSource.remark.like(keyword),
            )
        )
    if status:
        filters.append(models.UrlSource.status == status)
    if source_type:
        filters.append(models.UrlSource.source_type == source_type)
    if check_frequency:
        filters.append(models.UrlSource.check_frequency == check_frequency)
    for item in filters:
        statement = statement.where(item)
        count_statement = count_statement.where(item)
    total = db.scalar(count_statement) or 0
    items, next_cursor, has_more = cursor_window(db, statement, models.UrlSource.id, page_size, cursor)
    return schemas.UrlSourcePage(total=total, items=items, next_cursor=next_cursor, has_more=has_more)


@api.post("/url-sources", response_model=schemas.UrlSourceOut)
def create_url_source(payload: schemas.UrlSourceCreate, db: Session = Depends(get_db)):
    return crud.create_item(db, models.UrlSource, payload.model_dump(exclude_none=True))


@api.patch("/url-sources/{source_id}", response_model=schemas.UrlSourceOut)
def update_url_source(source_id: int, payload: schemas.UrlSourceUpdate, db: Session = Depends(get_db)):
    item = crud.get_item(db, models.UrlSource, source_id)
    if item is None:
        raise HTTPException(status_code=404, detail="URL 来源不存在")
    return crud.update_item(db, item, payload.model_dump(exclude_unset=True))


@api.post("/url-sources/{source_id}/check", response_model=schemas.UrlCheckResult)
def check_one_url_source(source_id: int, db: Session = Depends(get_db)):
    source = crud.get_item(db, models.UrlSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="URL 来源不存在")
    timeout_seconds = get_int_setting(db, "download_timeout_seconds", 30)
    return check_url_source(db, source, settings.storage_root, timeout_seconds)


@api.post("/url-sources/check-all", response_model=schemas.CheckAllResult)
def check_all_url_sources(include_manual: bool = False, db: Session = Depends(get_db)):
    include_manual = include_manual or get_bool_setting(db, "check_manual_in_batch", False)
    timeout_seconds = get_int_setting(db, "download_timeout_seconds", 30)
    total = 0
    results: list[schemas.UrlCheckResult] = []
    for source_ids in stream_url_source_ids(db, include_manual, 100):
        for source_id in source_ids:
            source = db.get(models.UrlSource, source_id)
            if source is None:
                continue
            result = check_url_source(db, source, settings.storage_root, timeout_seconds)
            total += 1
            if len(results) < 200:
                results.append(result)
    return schemas.CheckAllResult(total=total, results=results)


@api.post("/collection-tasks/url-check", response_model=schemas.CollectionTaskOut)
def create_url_check_task(
    payload: schemas.CollectionTaskCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    task = models.CollectionTask(
        task_type="url_check",
        status="pending",
        include_manual=payload.include_manual,
        batch_size=normalize_collection_batch_size(payload.batch_size),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    if settings.collection_task_inline_worker:
        background_tasks.add_task(
            run_url_check_task,
            task.id,
            payload.include_manual,
            normalize_collection_batch_size(payload.batch_size),
            f"fastapi-background-{task.id}",
        )
    return task


@api.post("/collection-tasks/{task_id}/resume", response_model=schemas.CollectionTaskOut)
def resume_collection_task(task_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    task = db.get(models.CollectionTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="采集任务不存在")
    if task.status == "finished":
        return task
    task.status = "pending"
    task.message = "已请求恢复执行"
    db.commit()
    db.refresh(task)
    if settings.collection_task_inline_worker:
        background_tasks.add_task(
            run_url_check_task,
            task.id,
            bool(task.include_manual),
            normalize_collection_batch_size(task.batch_size),
            f"fastapi-background-{task.id}",
        )
    return task


@api.get("/collection-tasks", response_model=list[schemas.CollectionTaskOut])
def list_collection_tasks(cursor: int | None = None, limit: int = 20, db: Session = Depends(get_db)):
    statement = select(models.CollectionTask)
    if cursor:
        statement = statement.where(models.CollectionTask.id < cursor)
    return list(db.scalars(statement.order_by(desc(models.CollectionTask.id)).limit(min(max(limit, 1), 100))))


@api.get("/documents", response_model=list[schemas.DocumentOut])
def list_documents(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    return crud.list_items(db, models.Document, skip, limit)


@api.get("/documents/page", response_model=schemas.DocumentPage)
def page_documents(
    page: int = 1,
    page_size: int = 50,
    cursor: int | None = None,
    q: str | None = None,
    valid_status: str | None = None,
    review_status: str | None = None,
    source_status: str | None = None,
    system_status: str | None = None,
    manual_status: str | None = None,
    doc_type: str | None = None,
    db: Session = Depends(get_db),
):
    page_size = min(max(page_size, 1), 200)
    statement = select(models.Document)
    count_statement = select(func.count(models.Document.id))
    filters = []
    if q:
        keyword = f"%{q}%"
        filters.append(
            or_(
                models.Document.title.like(keyword),
                models.Document.standard_no.like(keyword),
                models.Document.normalized_standard_no.like(keyword),
                models.Document.category.like(keyword),
                models.Document.issuing_authority.like(keyword),
            )
        )
    if valid_status:
        filters.append(models.Document.valid_status == valid_status)
    if review_status:
        filters.append(models.Document.review_status == review_status)
    if source_status:
        filters.append(models.Document.source_status == source_status)
    if system_status:
        filters.append(models.Document.system_status == system_status)
    if manual_status:
        filters.append(models.Document.manual_status == manual_status)
    if doc_type:
        filters.append(models.Document.doc_type == doc_type)
    for item in filters:
        statement = statement.where(item)
        count_statement = count_statement.where(item)
    total = db.scalar(count_statement) or 0
    items, next_cursor, has_more = cursor_window(db, statement, models.Document.id, page_size, cursor)
    return schemas.DocumentPage(total=total, items=items, next_cursor=next_cursor, has_more=has_more)


@api.post("/documents", response_model=schemas.DocumentOut)
def create_document(payload: schemas.DocumentCreate, db: Session = Depends(get_db)):
    item = models.Document(**payload.model_dump(exclude_none=True))
    apply_standard_number_fields(item, item.standard_no)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@api.patch("/documents/{document_id}", response_model=schemas.DocumentOut)
def update_document(document_id: int, payload: schemas.DocumentUpdate, db: Session = Depends(get_db)):
    item = crud.get_item(db, models.Document, document_id)
    if item is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    data = payload.model_dump(exclude_unset=True)
    old_manual_status = item.manual_status
    updated = crud.update_item(db, item, data)
    if "standard_no" in data:
        apply_standard_number_fields(updated, updated.standard_no)
    if "manual_status" in data and data.get("manual_status") != old_manual_status:
        manual_status = data.get("manual_status")
        if manual_status == "确认现行":
            updated.review_status = models.ReviewStatus.confirmed.value
            updated.valid_status = "现行"
        elif manual_status == "确认废止":
            updated.review_status = models.ReviewStatus.abolished.value
            updated.valid_status = "已废止"
        elif manual_status == "仅供参考":
            updated.review_status = models.ReviewStatus.reference.value
        elif manual_status == "暂不处理":
            updated.review_status = models.ReviewStatus.pending.value
        db.add(
            models.StandardEvidence(
                document_id=updated.id,
                source_name="人工复核",
                source_level="manual",
                source_url=None,
                raw_status_text=manual_status,
                parsed_status=manual_status,
                page_summary=updated.review_remark,
                evidence_note=f"人工复核状态由 {old_manual_status or '-'} 调整为 {manual_status or '-'}",
            )
        )
    if "valid_status" in data and "system_status" not in data:
        updated.system_status = data.get("valid_status")
    if "review_status" in data and "manual_status" not in data:
        updated.manual_status = data.get("review_status")
    if "standard_no" in data or "manual_status" in data or "valid_status" in data or "review_status" in data:
        db.commit()
        db.refresh(updated)
    return updated


@api.post("/documents/{document_id}/versions/upload", response_model=schemas.UploadVersionResponse)
async def upload_document_version(
    document_id: int,
    file: UploadFile = File(...),
    url_source_id: int | None = None,
    db: Session = Depends(get_db),
):
    document = crud.get_item(db, models.Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文件不存在")

    latest = db.scalars(
        select(models.DocumentVersion)
        .where(models.DocumentVersion.document_id == document_id, models.DocumentVersion.is_current.is_(True))
        .order_by(desc(models.DocumentVersion.downloaded_at))
    ).first()
    storage_status = check_storage_root(db, settings.storage_root)
    if not storage_status.available:
        raise HTTPException(status_code=400, detail=f"存储目录不可用：{storage_status.message}；目录：{storage_status.root}")
    target_path, size, file_hash = await save_upload(file, storage_status.root, document_id)
    duplicate = latest is not None and latest.file_hash == file_hash

    if latest and not duplicate:
        latest.is_current = False

    version = models.DocumentVersion(
        document_id=document_id,
        url_source_id=url_source_id,
        version_no=f"v{len(document.versions) + 1}",
        file_name=file.filename or target_path.name,
        file_path=relative_storage_path(storage_status.root, target_path),
        file_hash=file_hash,
        file_size=size,
        content_hash=file_hash,
        change_type=models.ChangeType.unchanged.value if duplicate else models.ChangeType.created.value,
        is_current=True,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return schemas.UploadVersionResponse.model_validate(version).model_copy(update={"duplicate": duplicate})


@api.get("/documents/{document_id}/versions", response_model=list[schemas.DocumentVersionOut])
def list_document_versions(document_id: int, db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(models.DocumentVersion)
            .where(models.DocumentVersion.document_id == document_id)
            .order_by(desc(models.DocumentVersion.downloaded_at))
        )
    )


@api.get("/document-versions/page", response_model=schemas.DocumentVersionPage)
def page_document_versions(
    page_size: int = 50,
    cursor: int | None = None,
    document_id: int | None = None,
    is_current: bool | None = None,
    db: Session = Depends(get_db),
):
    page_size = min(max(page_size, 1), 200)
    statement = select(models.DocumentVersion)
    count_statement = select(func.count(models.DocumentVersion.id))
    if document_id:
        statement = statement.where(models.DocumentVersion.document_id == document_id)
        count_statement = count_statement.where(models.DocumentVersion.document_id == document_id)
    if is_current is not None:
        statement = statement.where(models.DocumentVersion.is_current.is_(is_current))
        count_statement = count_statement.where(models.DocumentVersion.is_current.is_(is_current))
    total = db.scalar(count_statement) or 0
    items, next_cursor, has_more = cursor_window(db, statement, models.DocumentVersion.id, page_size, cursor)
    document_ids = [item.document_id for item in items]
    documents = (
        {
            document.id: document
            for document in db.scalars(select(models.Document).where(models.Document.id.in_(document_ids)))
        }
        if document_ids
        else {}
    )
    version_items = []
    for item in items:
        document = documents.get(item.document_id)
        version_items.append(
            schemas.DocumentVersionOut.model_validate(item).model_copy(
                update={
                    "document_title": document.title if document else None,
                    "standard_no": document.standard_no if document else None,
                }
            )
        )
    return schemas.DocumentVersionPage(total=total, items=version_items, next_cursor=next_cursor, has_more=has_more)


def resolve_document_version_file(db: Session, version: models.DocumentVersion) -> Path:
    storage_root = configured_storage_root(db, settings.storage_root).resolve()
    raw_path = Path(version.file_path)
    if raw_path.is_absolute():
        resolved = raw_path.resolve()
        try:
            resolved.relative_to(storage_root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="File path is outside the configured storage root.") from exc
        if resolved.exists() and resolved.is_file():
            return resolved
        raise HTTPException(status_code=404, detail="Archived file does not exist.")

    roots = [storage_root]
    fallback_roots = get_setting(db, "storage_fallback_roots", "") or ""
    for item in fallback_roots.split(";"):
        item = item.strip()
        if item:
            roots.append(Path(item).expanduser().resolve())

    for root in roots:
        resolved = (root / raw_path).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if resolved.exists() and resolved.is_file():
            return resolved
    raise HTTPException(status_code=404, detail="Archived file does not exist.")


def change_log_out(db: Session, log: models.StandardChangeLog) -> schemas.StandardChangeLogOut:
    document = db.get(models.Document, log.document_id) if log.document_id else None
    version = db.get(models.DocumentVersion, log.document_version_id) if log.document_version_id else None
    return schemas.StandardChangeLogOut.model_validate(log).model_copy(
        update={
            "document_title": document.title if document else None,
            "version_no": version.version_no if version else None,
            "file_name": version.file_name if version else None,
        }
    )


@api.get("/document-versions/{version_id}/file")
def get_document_version_file(version_id: int, inline: bool = True, db: Session = Depends(get_db)):
    version = db.get(models.DocumentVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Document version does not exist.")
    file_path = resolve_document_version_file(db, version)
    media_type, _encoding = mimetypes.guess_type(version.file_name or file_path.name)
    return FileResponse(
        file_path,
        media_type=media_type or "application/octet-stream",
        filename=version.file_name or file_path.name,
        content_disposition_type="inline" if inline else "attachment",
    )


@api.get("/alerts", response_model=list[schemas.AlertOut])
def list_alerts(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    return crud.list_items(db, models.Alert, skip, limit)


@api.get("/alerts/page", response_model=schemas.AlertPage)
def page_alerts(
    page: int = 1,
    page_size: int = 50,
    cursor: int | None = None,
    q: str | None = None,
    status: str | None = None,
    alert_type: str | None = None,
    alert_level: str | None = None,
    db: Session = Depends(get_db),
):
    page_size = min(max(page_size, 1), 200)
    statement = select(models.Alert)
    count_statement = select(func.count(models.Alert.id))
    filters = []
    if q:
        filters.append(models.Alert.message.like(f"%{q}%"))
    if status:
        filters.append(models.Alert.status == status)
    if alert_type:
        filters.append(models.Alert.alert_type == alert_type)
    if alert_level:
        filters.append(models.Alert.alert_level == alert_level)
    for item in filters:
        statement = statement.where(item)
        count_statement = count_statement.where(item)
    total = db.scalar(count_statement) or 0
    items, next_cursor, has_more = cursor_window(db, statement, models.Alert.id, page_size, cursor)
    return schemas.AlertPage(total=total, items=items, next_cursor=next_cursor, has_more=has_more)


@api.post("/alerts", response_model=schemas.AlertOut)
def create_alert(payload: schemas.AlertCreate, db: Session = Depends(get_db)):
    return crud.create_item(db, models.Alert, payload.model_dump(exclude_none=True))


@api.patch("/alerts/{alert_id}", response_model=schemas.AlertOut)
def update_alert(alert_id: int, payload: schemas.AlertUpdate, db: Session = Depends(get_db)):
    item = crud.get_item(db, models.Alert, alert_id)
    if item is None:
        raise HTTPException(status_code=404, detail="提醒不存在")
    data = payload.model_dump(exclude_unset=True)
    if data.get("status") in {models.AlertStatus.handled.value, models.AlertStatus.ignored.value} and not data.get(
        "handled_at"
    ):
        data["handled_at"] = datetime.now(UTC)
    return crud.update_item(db, item, data)


@api.get("/check-logs/page", response_model=schemas.CheckLogPage)
def page_check_logs(
    page: int = 1,
    page_size: int = 50,
    cursor: int | None = None,
    url_source_id: int | None = None,
    result: str | None = None,
    db: Session = Depends(get_db),
):
    page_size = min(max(page_size, 1), 200)
    statement = select(models.CheckLog)
    count_statement = select(func.count(models.CheckLog.id))
    if url_source_id:
        statement = statement.where(models.CheckLog.url_source_id == url_source_id)
        count_statement = count_statement.where(models.CheckLog.url_source_id == url_source_id)
    if result:
        statement = statement.where(models.CheckLog.result == result)
        count_statement = count_statement.where(models.CheckLog.result == result)
    total = db.scalar(count_statement) or 0
    items, next_cursor, has_more = cursor_window(db, statement, models.CheckLog.id, page_size, cursor)
    return schemas.CheckLogPage(total=total, items=items, next_cursor=next_cursor, has_more=has_more)


@api.get("/categories", response_model=list[schemas.CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return list(db.scalars(select(models.Category).order_by(models.Category.sort_order, models.Category.id)))


@api.post("/categories", response_model=schemas.CategoryOut)
def create_category(payload: schemas.CategoryCreate, db: Session = Depends(get_db)):
    return crud.create_item(db, models.Category, payload.model_dump(exclude_none=True))


@api.get("/settings", response_model=list[schemas.SystemSettingOut])
def list_settings(db: Session = Depends(get_db)):
    ensure_default_settings(db)
    return list(db.scalars(select(models.SystemSetting).order_by(models.SystemSetting.key)))


@api.patch("/settings/{key}", response_model=schemas.SystemSettingOut)
def update_setting(key: str, payload: schemas.SystemSettingUpdate, db: Session = Depends(get_db)):
    ensure_default_settings(db)
    item = db.get(models.SystemSetting, key)
    if item is None:
        raise HTTPException(status_code=404, detail="系统设置不存在")
    item.value = payload.value
    db.commit()
    db.refresh(item)
    return item


@api.get("/storage/status", response_model=schemas.StorageStatusOut)
def get_storage_status(db: Session = Depends(get_db)):
    ensure_default_settings(db)
    status = check_storage_root(db, settings.storage_root)
    return schemas.StorageStatusOut(
        root=str(status.root),
        available=status.available,
        exists=status.exists,
        is_dir=status.is_dir,
        writable=status.writable,
        auto_create=status.auto_create,
        pause_download_if_unavailable=status.pause_download_if_unavailable,
        message=status.message,
    )


@api.get("/storage/browse", response_model=schemas.StorageBrowseOut)
def browse_storage_directories(path: str | None = None):
    if path:
        current = Path(path).expanduser()
        if not current.is_absolute():
            current = (Path.cwd() / current).resolve()
        if not current.exists() or not current.is_dir():
            raise HTTPException(status_code=404, detail="目录不存在")
        directories = []
        try:
            children = sorted(
                [item for item in current.iterdir() if item.is_dir()],
                key=lambda item: item.name.lower(),
            )
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"目录不可访问：{exc}") from exc
        for item in children:
            directories.append(schemas.StorageDirectoryItem(name=item.name, path=str(item)))
        parent = str(current.parent) if current.parent != current else None
        return schemas.StorageBrowseOut(path=str(current), parent=parent, directories=directories)

    directories = []
    if string.ascii_uppercase and Path("C:/").exists():
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:/")
            if drive.exists():
                directories.append(schemas.StorageDirectoryItem(name=f"{letter}:\\", path=str(drive)))
    home = Path.home()
    if home.exists():
        directories.append(schemas.StorageDirectoryItem(name="用户目录", path=str(home)))
    return schemas.StorageBrowseOut(path=None, parent=None, directories=directories)


@api.get("/trusted-sources", response_model=list[schemas.TrustedSourceOut])
def list_trusted_sources(include_disabled: bool = False, db: Session = Depends(get_db)):
    ensure_default_trusted_sources(db)
    statement = select(models.TrustedSource).order_by(models.TrustedSource.id)
    if not include_disabled:
        statement = statement.where(models.TrustedSource.enabled.is_(True))
    return list(db.scalars(statement))


@api.get("/trusted-sources/{source_id}/categories", response_model=list[schemas.SourceCategoryOut])
def list_trusted_source_categories(source_id: int, db: Session = Depends(get_db)):
    source = db.get(models.TrustedSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="可信源不存在")
    return list(
        db.scalars(
            select(models.SourceCategory)
            .where(models.SourceCategory.source_id == source_id)
            .order_by(models.SourceCategory.category_path, models.SourceCategory.source_category_id)
        )
    )


@api.get("/trusted-sources/{source_id}/categories/page", response_model=schemas.SourceCategoryPage)
def page_trusted_source_categories(
    source_id: int,
    page: int = 1,
    page_size: int = 50,
    cursor: int | None = None,
    q: str | None = None,
    sync_status: str | None = None,
    db: Session = Depends(get_db),
):
    source = db.get(models.TrustedSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="可信源不存在")
    page_size = min(max(page_size, 1), 200)
    statement = select(models.SourceCategory).where(models.SourceCategory.source_id == source_id)
    count_statement = select(func.count(models.SourceCategory.id)).where(models.SourceCategory.source_id == source_id)
    filters = []
    if q:
        keyword = f"%{q}%"
        filters.append(
            or_(
                models.SourceCategory.source_category_id.like(keyword),
                models.SourceCategory.category_name.like(keyword),
                models.SourceCategory.category_path.like(keyword),
            )
        )
    if sync_status:
        filters.append(models.SourceCategory.sync_status == sync_status)
    for item in filters:
        statement = statement.where(item)
        count_statement = count_statement.where(item)
    total = db.scalar(count_statement) or 0
    items, next_cursor, has_more = cursor_window(db, statement, models.SourceCategory.id, page_size, cursor)
    return schemas.SourceCategoryPage(total=total, items=items, next_cursor=next_cursor, has_more=has_more)


@api.post("/trusted-sources/{source_id}/discover-categories", response_model=schemas.CategoryDiscoveryResult)
def discover_trusted_source_categories(source_id: int, db: Session = Depends(get_db)):
    source = db.get(models.TrustedSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="可信源不存在")
    if source.adapter_key != "guobiao_ebook":
        raise HTTPException(status_code=400, detail="当前仅国标电子书库支持自动发现分类")
    return schemas.CategoryDiscoveryResult(**sync_discovered_sublibs(db, source))


@api.get("/standard-resources/page", response_model=schemas.StandardResourcePage)
def page_standard_resources(
    page: int = 1,
    page_size: int = 50,
    cursor: int | None = None,
    source_id: int | None = None,
    source_category_id: str | None = None,
    q: str | None = None,
    source_status: str | None = None,
    resource_type: str | None = None,
    db: Session = Depends(get_db),
):
    page_size = min(max(page_size, 1), 200)
    statement = select(models.StandardResource)
    count_statement = select(func.count(models.StandardResource.id))
    filters = []
    if q:
        keyword = f"%{q}%"
        filters.append(
            or_(
                models.StandardResource.standard_no.like(keyword),
                models.StandardResource.normalized_standard_no.like(keyword),
                models.StandardResource.standard_name.like(keyword),
                models.StandardResource.keywords.like(keyword),
                models.StandardResource.source_category_path.like(keyword),
            )
        )
    if source_id:
        filters.append(models.StandardResource.source_id == source_id)
    if source_category_id:
        category_statement = select(models.SourceCategory).where(
            models.SourceCategory.source_category_id == source_category_id
        )
        if source_id:
            category_statement = category_statement.where(models.SourceCategory.source_id == source_id)
        category = db.scalars(category_statement.order_by(models.SourceCategory.id)).first()
        if category and category.category_path:
            filters.append(models.StandardResource.source_category_path == category.category_path)
        else:
            filters.append(models.StandardResource.source_category_path == source_category_id)
    if source_status:
        filters.append(models.StandardResource.source_status == source_status)
    if resource_type:
        filters.append(models.StandardResource.resource_type == resource_type)
    for item in filters:
        statement = statement.where(item)
        count_statement = count_statement.where(item)
    total = db.scalar(count_statement) or 0
    items, next_cursor, has_more = cursor_window(db, statement, models.StandardResource.id, page_size, cursor)
    return schemas.StandardResourcePage(total=total, items=items, next_cursor=next_cursor, has_more=has_more)


@api.post(
    "/standard-resources/{resource_id}/download-captcha",
    response_model=schemas.ResourceDownloadCaptchaChallenge,
)
def create_resource_download_captcha(resource_id: int, db: Session = Depends(get_db)):
    resource = db.get(models.StandardResource, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="可信源资源不存在")
    hcno = extract_hcno(resource)
    if not hcno:
        raise HTTPException(status_code=400, detail="该标准暂未入库官方全文入口，无法生成验证码")

    download_page_url = _download_url(hcno)
    captcha_url = f"{GB688_BASE_URL}/gc?_{int(time.time() * 1000)}"
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=get_int_setting(db, "download_timeout_seconds", 30),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StandardDocsIngest/1.0",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        ) as client:
            page = client.get(download_page_url, headers={"Accept": "text/html,*/*", "Referer": _online_url(hcno)})
            page.raise_for_status()
            captcha = client.get(captcha_url, headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"})
            captcha.raise_for_status()
            content_type = captcha.headers.get("content-type") or "image/jpeg"
            if not content_type.lower().startswith("image/"):
                raise HTTPException(status_code=502, detail=f"验证码接口返回异常：{content_type}")
            challenge_id = secrets.token_urlsafe(24)
            expires_at = datetime.now(UTC) + timedelta(seconds=CAPTCHA_CHALLENGE_TTL_SECONDS)
            captcha_challenges()[challenge_id] = {
                "resource_id": resource.id,
                "hcno": hcno,
                "cookies": dict(client.cookies),
                "expires_at": expires_at,
            }
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"获取官方验证码失败：{exc}") from exc

    return schemas.ResourceDownloadCaptchaChallenge(
        resource_id=resource.id,
        challenge_id=challenge_id,
        captcha_image_base64=base64.b64encode(captcha.content).decode("ascii"),
        captcha_content_type=content_type,
        expires_at=expires_at,
        message="请输入图片验证码后下载真实 PDF；验证码只用于本次官方下载会话。",
    )


@api.post("/standard-resources/{resource_id}/download-with-captcha", response_model=schemas.UrlCheckResult)
def download_resource_with_captcha(
    resource_id: int,
    payload: schemas.ResourceDownloadCaptchaSubmit,
    db: Session = Depends(get_db),
):
    resource = db.get(models.StandardResource, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="可信源资源不存在")
    challenge = captcha_challenges().pop(payload.challenge_id, None)
    if not challenge or challenge.get("resource_id") != resource.id:
        raise HTTPException(status_code=400, detail="验证码会话不存在或已过期，请刷新验证码")
    verify_code = (payload.verify_code or "").strip()
    if not verify_code:
        raise HTTPException(status_code=400, detail="请输入验证码")

    hcno = challenge["hcno"]
    cookies = challenge.get("cookies") or {}
    verify_url = f"{GB688_BASE_URL}/verifyCode"
    file_url = f"{GB688_BASE_URL}/viewGb?hcno={hcno}"
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=get_int_setting(db, "download_timeout_seconds", 30),
            cookies=cookies,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StandardDocsIngest/1.0",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        ) as client:
            verify = client.post(
                verify_url,
                data={"verifyCode": verify_code},
                headers={
                    "Accept": "text/plain,*/*",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": _download_url(hcno),
                },
            )
            verify.raise_for_status()
            if verify.text.strip() != "success":
                raise HTTPException(status_code=400, detail="验证码不正确，请重新获取验证码后重试")
            response = client.get(
                file_url,
                headers={"Accept": "application/pdf,*/*", "Referer": _download_url(hcno)},
            )
            response.raise_for_status()
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"官方文件下载失败：{exc}") from exc

    content_type = response.headers.get("content-type") or ""
    if not response.content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail=f"官方返回内容不是 PDF，已拒绝入库：{content_type or 'unknown'}")

    url_source = create_or_get_download_url_source(db, resource, file_url)
    result = archive_downloaded_content(
        db,
        url_source,
        settings.storage_root,
        DownloadedContent(
            status_code=response.status_code,
            url=str(response.url),
            content=response.content,
            content_type=content_type,
            content_disposition=response.headers.get("content-disposition"),
        ),
    )
    if result.ok:
        db.refresh(resource)
        calibrate_resource_status(db, resource)
        db.commit()
    return result


@api.get("/standard-file-matches", response_model=list[schemas.StandardFileMatchOut])
def list_standard_file_matches(limit: int = 100, db: Session = Depends(get_db)):
    return list(db.scalars(select(models.StandardFileMatch).order_by(desc(models.StandardFileMatch.id)).limit(limit)))


@api.get("/standard-file-matches/page", response_model=schemas.StandardFileMatchPage)
def page_standard_file_matches(
    page_size: int = 50,
    cursor: int | None = None,
    db: Session = Depends(get_db),
):
    page_size = min(max(page_size, 1), 200)
    statement = select(models.StandardFileMatch)
    total = db.scalar(select(func.count(models.StandardFileMatch.id))) or 0
    items, next_cursor, has_more = cursor_window(db, statement, models.StandardFileMatch.id, page_size, cursor)
    return schemas.StandardFileMatchPage(total=total, items=items, next_cursor=next_cursor, has_more=has_more)


@api.get("/standard-change-logs", response_model=list[schemas.StandardChangeLogOut])
def list_standard_change_logs(limit: int = 100, db: Session = Depends(get_db)):
    logs = list(
        db.scalars(
            select(models.StandardChangeLog)
            .where(models.StandardChangeLog.field_name != "detail_hash")
            .order_by(desc(models.StandardChangeLog.id))
            .limit(limit)
        )
    )
    return [change_log_out(db, item) for item in logs]


@api.get("/standard-change-logs/page", response_model=schemas.StandardChangeLogPage)
def page_standard_change_logs(
    page_size: int = 50,
    cursor: int | None = None,
    db: Session = Depends(get_db),
):
    page_size = min(max(page_size, 1), 200)
    statement = select(models.StandardChangeLog).where(models.StandardChangeLog.field_name != "detail_hash")
    total = db.scalar(
        select(func.count(models.StandardChangeLog.id)).where(models.StandardChangeLog.field_name != "detail_hash")
    ) or 0
    items, next_cursor, has_more = cursor_window(db, statement, models.StandardChangeLog.id, page_size, cursor)
    return schemas.StandardChangeLogPage(
        total=total,
        items=[change_log_out(db, item) for item in items],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@api.get("/source-status-sync-logs", response_model=list[schemas.SourceStatusSyncLogOut])
def list_source_status_sync_logs(limit: int = 100, db: Session = Depends(get_db)):
    return list(db.scalars(select(models.SourceStatusSyncLog).order_by(desc(models.SourceStatusSyncLog.id)).limit(limit)))


@api.get("/source-status-sync-logs/page", response_model=schemas.SourceStatusSyncLogPage)
def page_source_status_sync_logs(
    page_size: int = 50,
    cursor: int | None = None,
    db: Session = Depends(get_db),
):
    page_size = min(max(page_size, 1), 200)
    statement = select(models.SourceStatusSyncLog)
    total = db.scalar(select(func.count(models.SourceStatusSyncLog.id))) or 0
    items, next_cursor, has_more = cursor_window(db, statement, models.SourceStatusSyncLog.id, page_size, cursor)
    return schemas.SourceStatusSyncLogPage(total=total, items=items, next_cursor=next_cursor, has_more=has_more)


@api.patch("/standard-relations/{relation_id}", response_model=schemas.StandardRelationOut)
def update_standard_relation(relation_id: int, payload: schemas.StandardRelationUpdate, db: Session = Depends(get_db)):
    relation = db.get(models.StandardRelation, relation_id)
    if relation is None:
        raise HTTPException(status_code=404, detail="替代/相关关系不存在")
    data = payload.model_dump(exclude_unset=True)
    for field_name, value in data.items():
        setattr(relation, field_name, value)
    db.commit()
    db.refresh(relation)
    return relation


@api.post("/standard-file-matches/run", response_model=schemas.MatchRunResult)
def run_standard_file_match(cursor: int | None = None, batch_size: int = 500, db: Session = Depends(get_db)):
    batch_size = min(max(batch_size, 1), 5000)
    matched = 0
    skipped = 0
    processed = 0
    document_statement = select(models.Document).where(models.Document.standard_no.is_not(None))
    if cursor:
        document_statement = document_statement.where(models.Document.id > cursor)
    documents = list(db.scalars(document_statement.order_by(models.Document.id).limit(batch_size + 1)))
    has_more = len(documents) > batch_size
    documents = documents[:batch_size]
    next_cursor = documents[-1].id if has_more and documents else None
    for document in documents:
        processed += 1
        if document.standard_no and not document.normalized_standard_no:
            apply_standard_number_fields(document, document.standard_no)
        standard_no = (document.normalized_standard_no or normalize_standard_no(document.standard_no).normalized or "").strip()
        candidates = list(
            db.scalars(
                select(models.StandardResource)
                .where(
                    or_(
                        models.StandardResource.normalized_standard_no == standard_no,
                        models.StandardResource.standard_no == document.standard_no,
                    )
                )
                .order_by(models.StandardResource.id)
                .limit(20)
            )
        )
        if not candidates:
            skipped += 1
            continue
        best = max(
            candidates,
            key=lambda item: SequenceMatcher(None, document.title or "", item.standard_name or "").ratio(),
        )
        score = int(SequenceMatcher(None, document.title or "", best.standard_name or "").ratio() * 100)
        exists = db.scalars(
            select(models.StandardFileMatch).where(
                models.StandardFileMatch.standard_resource_id == best.id,
                models.StandardFileMatch.document_id == document.id,
            )
        ).first()
        if exists:
            calibration = calibrate_resource_status(db, best)
            matched += calibration["matches"]
            continue

        # calibrate_resource_status owns match creation, status backfill, evidence,
        # sync logs, and alerts. Keeping match creation in one place avoids duplicate
        # pending inserts for the same resource/document pair during large batches.
        calibration = calibrate_resource_status(db, best)
        if calibration["matches"]:
            matched += calibration["matches"]
        else:
            skipped += 1
    db.commit()
    return schemas.MatchRunResult(matched=matched, skipped=skipped, processed=processed, next_cursor=next_cursor, has_more=has_more)


@api.get("/standard-resources/{resource_id}/chain", response_model=schemas.ResourceChainOut)
def get_standard_resource_chain(resource_id: int, db: Session = Depends(get_db)):
    resource = db.get(models.StandardResource, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="可信源资源不存在")
    details = list(
        db.scalars(
            select(models.StandardDetail)
            .where(models.StandardDetail.standard_resource_id == resource_id)
            .order_by(desc(models.StandardDetail.captured_at))
        )
    )
    matches = list(
        db.scalars(
            select(models.StandardFileMatch)
            .where(models.StandardFileMatch.standard_resource_id == resource_id)
            .order_by(desc(models.StandardFileMatch.id))
        )
    )
    document_ids = [item.document_id for item in matches]
    documents = list(db.scalars(select(models.Document).where(models.Document.id.in_(document_ids)))) if document_ids else []
    versions = (
        list(db.scalars(select(models.DocumentVersion).where(models.DocumentVersion.document_id.in_(document_ids))))
        if document_ids
        else []
    )
    source_ids = sorted({version.url_source_id for version in versions if version.url_source_id})
    url_sources = list(db.scalars(select(models.UrlSource).where(models.UrlSource.id.in_(source_ids)))) if source_ids else []
    change_logs = list(
        db.scalars(
            select(models.StandardChangeLog)
            .where(models.StandardChangeLog.standard_resource_id == resource_id)
            .where(models.StandardChangeLog.field_name != "detail_hash")
            .order_by(desc(models.StandardChangeLog.detected_at))
        )
    )
    sync_logs = list(
        db.scalars(
            select(models.SourceStatusSyncLog)
            .where(models.SourceStatusSyncLog.standard_resource_id == resource_id)
            .order_by(desc(models.SourceStatusSyncLog.synced_at))
        )
    )
    evidences = list(
        db.scalars(
            select(models.StandardEvidence)
            .where(
                or_(
                    models.StandardEvidence.standard_resource_id == resource_id,
                    models.StandardEvidence.document_id.in_(document_ids) if document_ids else False,
                )
            )
            .order_by(desc(models.StandardEvidence.captured_at))
        )
    )
    relation_no = resource.normalized_standard_no or resource.standard_no
    relations = list(
        db.scalars(
            select(models.StandardRelation)
            .where(
                or_(
                    models.StandardRelation.current_standard_resource_id == resource_id,
                    models.StandardRelation.related_standard_resource_id == resource_id,
                    models.StandardRelation.current_standard_no == relation_no,
                    models.StandardRelation.related_standard_no == relation_no,
                )
            )
            .order_by(desc(models.StandardRelation.discovered_at))
        )
    )
    alerts = list(db.scalars(select(models.Alert).where(models.Alert.document_id.in_(document_ids)))) if document_ids else []
    return schemas.ResourceChainOut(
        resource=resource,
        details=details,
        matches=matches,
        documents=documents,
        versions=versions,
        url_sources=url_sources,
        change_logs=[change_log_out(db, item) for item in change_logs],
        sync_logs=sync_logs,
        evidences=evidences,
        relations=relations,
        alerts=alerts,
        processing_advice=chain_processing_advice(
            resource.source_status,
            resource.system_status,
            resource.manual_status,
            len(matches),
            len([alert for alert in alerts if alert.status == models.AlertStatus.pending.value]),
        ),
    )


@api.get("/documents/{document_id}/chain", response_model=schemas.DocumentChainOut)
def get_document_chain(document_id: int, db: Session = Depends(get_db)):
    document = db.get(models.Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    versions = list(
        db.scalars(
            select(models.DocumentVersion)
            .where(models.DocumentVersion.document_id == document_id)
            .order_by(desc(models.DocumentVersion.downloaded_at))
        )
    )
    matches = list(
        db.scalars(
            select(models.StandardFileMatch)
            .where(models.StandardFileMatch.document_id == document_id)
            .order_by(desc(models.StandardFileMatch.id))
        )
    )
    resource_ids = [item.standard_resource_id for item in matches]
    resources = (
        list(db.scalars(select(models.StandardResource).where(models.StandardResource.id.in_(resource_ids))))
        if resource_ids
        else []
    )
    source_ids = sorted({version.url_source_id for version in versions if version.url_source_id})
    url_sources = list(db.scalars(select(models.UrlSource).where(models.UrlSource.id.in_(source_ids)))) if source_ids else []
    change_logs = list(
        db.scalars(
            select(models.StandardChangeLog)
            .where(models.StandardChangeLog.document_id == document_id)
            .where(models.StandardChangeLog.field_name != "detail_hash")
            .order_by(desc(models.StandardChangeLog.detected_at))
        )
    )
    sync_logs = list(
        db.scalars(
            select(models.SourceStatusSyncLog)
            .where(models.SourceStatusSyncLog.document_id == document_id)
            .order_by(desc(models.SourceStatusSyncLog.synced_at))
        )
    )
    evidences = list(
        db.scalars(
            select(models.StandardEvidence)
            .where(
                or_(
                    models.StandardEvidence.document_id == document_id,
                    models.StandardEvidence.standard_resource_id.in_(resource_ids) if resource_ids else False,
                )
            )
            .order_by(desc(models.StandardEvidence.captured_at))
        )
    )
    relation_numbers = {resource.normalized_standard_no or resource.standard_no for resource in resources}
    relation_numbers.add(document.normalized_standard_no or document.standard_no)
    relation_numbers.discard(None)
    relations = (
        list(
            db.scalars(
                select(models.StandardRelation)
                .where(
                    or_(
                        models.StandardRelation.current_standard_resource_id.in_(resource_ids) if resource_ids else False,
                        models.StandardRelation.related_standard_resource_id.in_(resource_ids) if resource_ids else False,
                        models.StandardRelation.current_standard_no.in_(relation_numbers),
                        models.StandardRelation.related_standard_no.in_(relation_numbers),
                    )
                )
                .order_by(desc(models.StandardRelation.discovered_at))
            )
        )
        if relation_numbers or resource_ids
        else []
    )
    alerts = list(
        db.scalars(select(models.Alert).where(models.Alert.document_id == document_id).order_by(desc(models.Alert.id)))
    )
    return schemas.DocumentChainOut(
        document=document,
        versions=versions,
        matches=matches,
        resources=resources,
        url_sources=url_sources,
        change_logs=[change_log_out(db, item) for item in change_logs],
        sync_logs=sync_logs,
        evidences=evidences,
        relations=relations,
        alerts=alerts,
        processing_advice=chain_processing_advice(
            document.source_status,
            document.system_status or document.valid_status,
            document.manual_status or document.review_status,
            len(matches),
            len([alert for alert in alerts if alert.status == models.AlertStatus.pending.value]),
        ),
    )


@api.post("/trusted-sources/guobiao/sync", response_model=schemas.GuobiaoSyncResult)
def sync_guobiao(payload: schemas.GuobiaoSyncRequest, db: Session = Depends(get_db)):
    max_pages = min(max(payload.max_pages_per_sublib, 1), 10)
    result = sync_guobiao_resources(
        db,
        max_pages_per_sublib=max_pages,
        include_detail=payload.include_detail,
        sublib_id=payload.sublib_id,
    )
    return schemas.GuobiaoSyncResult(**result)


@api.post("/trusted-sources/sync", response_model=schemas.GuobiaoSyncResult)
def sync_trusted_source(payload: schemas.TrustedSourceSyncRequest, db: Session = Depends(get_db)):
    source = db.get(models.TrustedSource, payload.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="可信源不存在")
    if not source.adapter_key:
        raise HTTPException(status_code=400, detail="该可信源未配置采集适配器")
    adapter = registry.get(source.adapter_key)
    if adapter is None:
        raise HTTPException(status_code=400, detail=f"未找到适配器：{source.adapter_key}")
    result = adapter.sync(
        db,
        source.id,
        TrustedSourceSyncOptions(
            max_pages=min(max(payload.max_pages, 1), 10),
            include_detail=payload.include_detail,
            category_id=payload.category_id,
            only_pending_categories=payload.only_pending_categories,
            category_limit=min(max(payload.category_limit or 0, 0), 100) or None,
        ),
    )
    return schemas.GuobiaoSyncResult(**result.__dict__)


app.mount(settings.api_prefix, api)
