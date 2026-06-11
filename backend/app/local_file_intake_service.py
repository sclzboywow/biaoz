from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.download_service import doc_type
from app.settings_store import get_bool_setting
from app.standard_number import canonicalize_standard_no_text, extract_standard_no_from_text, normalize_standard_no
from app.status_calibration import calibrate_resource_status, link_archived_document_to_resources
from app.storage import (
    check_storage_root,
    filesystem_safe_filename,
    relative_storage_path,
    safe_stem,
    safe_suffix,
    safe_upload_filename,
    sha256_file,
)
from app.intake_search_slices import build_intake_search_queries
from app.trusted_source_adapters import TrustedSourceSearchQuery
from app.trusted_source_search_service import search_trusted_sources, search_trusted_sources_sliced

settings = get_settings()

DECISION_LABELS = {
    "duplicate_ignore": "重复忽略",
    "link_existing": "关联已有",
    "create_document": "新建入库",
    "need_review": "待复核",
}

RISK_LABELS = {
    "low": "低",
    "medium": "中",
    "high": "高",
}


@dataclass
class ExtractedMetadata:
    standard_no: str | None = None
    normalized_standard_no: str | None = None
    title: str | None = None
    publish_date: date | None = None
    effective_date: date | None = None
    text_sample: str | None = None
    page_count: int | None = None
    file_type: str | None = None
    mime_type: str | None = None


def _similarity(left: str | None, right: str | None) -> int:
    return int(SequenceMatcher(None, left or "", right or "").ratio() * 100)


def _append_log(db: Session, task_id: int, step_name: str, result: str, message: str | None = None, detail: dict | None = None) -> None:
    db.add(
        models.LocalFileIntakeLog(
            task_id=task_id,
            step_name=step_name,
            result=result,
            message=message,
            detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
        )
    )


def _intake_temp_dir(storage_root: Path, task_id: int) -> Path:
    target = storage_root / "local-intake" / str(task_id)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _extract_standard_no_from_text(text: str) -> str | None:
    return extract_standard_no_from_text(text)


def _strip_standard_no_from_title(stem: str, standard_no: str | None) -> str:
    if not standard_no:
        return stem
    title = stem
    fragments = {
        standard_no,
        standard_no.replace("/", "-"),
        standard_no.replace("/", ""),
        standard_no.replace(" ", ""),
    }
    parts = normalize_standard_no(standard_no)
    if parts.normalized:
        fragments.add(parts.normalized)
        fragments.add(parts.normalized.replace("/", "-"))
        fragments.add(parts.normalized.replace(" ", ""))
        if "/" in parts.normalized:
            fragments.add(parts.normalized.replace("/", " "))
            head, _, tail = parts.normalized.partition("/")
            if tail:
                fragments.add(f"{head}-{tail}")
                fragments.add(f"{head} {tail}")
    recanon = extract_standard_no_from_text(canonicalize_standard_no_text(stem))
    if recanon:
        fragments.add(recanon)
    for fragment in sorted(fragments, key=len, reverse=True):
        if fragment:
            title = re.sub(re.escape(fragment), "", title, count=1, flags=re.I)
    title = re.sub(r"^[\s\-_]+|[\s\-_]+$", "", title)
    title = re.sub(r"[\s\-_]{2,}", " ", title).strip()
    return title or stem


def extract_local_file_metadata(file_path: Path, *, original_name: str | None = None, mime_type: str | None = None) -> ExtractedMetadata:
    name = original_name or safe_upload_filename(file_path.name)
    stem = safe_stem(name)
    suffix = safe_suffix(name)
    standard_no = _extract_standard_no_from_text(stem) or _extract_standard_no_from_text(name)
    number_parts = normalize_standard_no(standard_no)
    title = _strip_standard_no_from_title(stem, standard_no)
    return ExtractedMetadata(
        standard_no=number_parts.raw or standard_no,
        normalized_standard_no=number_parts.normalized,
        title=title or stem,
        text_sample=stem[:500],
        page_count=None,
        file_type=suffix.upper() if suffix else None,
        mime_type=mime_type,
    )


def _apply_metadata(task: models.LocalFileIntakeTask, metadata: ExtractedMetadata) -> None:
    task.extracted_standard_no = metadata.standard_no
    task.normalized_standard_no = metadata.normalized_standard_no
    task.extracted_title = metadata.title
    task.extracted_text_sample = metadata.text_sample
    task.page_count = metadata.page_count
    task.file_type = metadata.file_type
    task.mime_type = metadata.mime_type


async def create_intake_task(db: Session, upload_file: UploadFile) -> models.LocalFileIntakeTask:
    storage_status = check_storage_root(db, settings.storage_root)
    if not storage_status.available:
        raise ValueError(f"存储目录不可用：{storage_status.message}")

    safe_name = safe_upload_filename(upload_file.filename)
    disk_name = filesystem_safe_filename(upload_file.filename)
    staging_dir = storage_status.root / "local-intake" / "pending" / uuid4().hex
    staging_dir.mkdir(parents=True, exist_ok=True)
    target_path = staging_dir / disk_name

    size = 0
    with target_path.open("wb") as file_obj:
        while chunk := await upload_file.read(1024 * 1024):
            size += len(chunk)
            file_obj.write(chunk)

    file_hash = sha256_file(target_path)
    metadata = extract_local_file_metadata(
        target_path,
        original_name=safe_name,
        mime_type=upload_file.content_type,
    )

    task = models.LocalFileIntakeTask(
        original_file_name=safe_name,
        temp_file_path=relative_storage_path(storage_status.root, target_path),
        file_hash=file_hash,
        file_size=size,
        file_type=metadata.file_type,
        mime_type=metadata.mime_type,
        recognition_status="pending",
    )
    _apply_metadata(task, metadata)
    db.add(task)
    db.flush()

    final_dir = _intake_temp_dir(storage_status.root, task.id)
    final_path = final_dir / disk_name
    target_path.replace(final_path)
    task.temp_file_path = relative_storage_path(storage_status.root, final_path)
    staging_dir.rmdir() if staging_dir.exists() and not any(staging_dir.iterdir()) else None

    _append_log(db, task.id, "upload", "ok", f"已保存临时文件：{safe_name}", {"file_hash": file_hash, "file_size": size})
    db.commit()
    db.refresh(task)
    return task


def match_existing_versions(db: Session, task: models.LocalFileIntakeTask) -> list[models.LocalFileRecognitionCandidate]:
    candidates: list[models.LocalFileRecognitionCandidate] = []
    for version in db.scalars(
        select(models.DocumentVersion)
        .where(models.DocumentVersion.file_hash == task.file_hash)
        .order_by(desc(models.DocumentVersion.is_current), desc(models.DocumentVersion.id))
        .limit(10)
    ):
        document = db.get(models.Document, version.document_id)
        candidates.append(
            models.LocalFileRecognitionCandidate(
                task_id=task.id,
                candidate_type="document_version",
                candidate_id=version.id,
                source_name="本地归档库",
                standard_no=document.standard_no if document else None,
                normalized_standard_no=document.normalized_standard_no if document else None,
                standard_name=document.title if document else version.file_name,
                match_score=100,
                match_reason=f"文件 hash 与版本 #{version.id} 完全一致",
                decision_advice="duplicate_ignore",
            )
        )
    return candidates


def match_existing_documents(db: Session, task: models.LocalFileIntakeTask) -> list[models.LocalFileRecognitionCandidate]:
    if not task.normalized_standard_no and not task.extracted_standard_no:
        return []

    number = task.normalized_standard_no or normalize_standard_no(task.extracted_standard_no).normalized
    if not number:
        return []

    candidates: list[models.LocalFileRecognitionCandidate] = []
    for document in db.scalars(
        select(models.Document).where(
            or_(
                models.Document.normalized_standard_no == number,
                models.Document.standard_no == task.extracted_standard_no,
            )
        )
        .order_by(desc(models.Document.updated_at), desc(models.Document.id))
        .limit(10)
    ):
        title_score = _similarity(task.extracted_title, document.title)
        advice = "link_existing" if title_score >= 60 else "need_review"
        candidates.append(
            models.LocalFileRecognitionCandidate(
                task_id=task.id,
                candidate_type="document",
                candidate_id=document.id,
                source_name="本地标准文件",
                standard_no=document.standard_no,
                normalized_standard_no=document.normalized_standard_no,
                standard_name=document.title,
                source_status=document.valid_status,
                publish_date=document.publish_date,
                effective_date=document.effective_date,
                match_score=max(70, title_score),
                match_reason=f"标准编号一致（{number}），标题相似度 {title_score}%",
                decision_advice=advice,
            )
        )
    return candidates


def match_standard_resources(db: Session, task: models.LocalFileIntakeTask) -> list[models.LocalFileRecognitionCandidate]:
    query = TrustedSourceSearchQuery(
        standard_no=task.extracted_standard_no,
        normalized_standard_no=task.normalized_standard_no,
        standard_name=task.extracted_title,
    )
    if not (query.standard_no or query.normalized_standard_no or query.standard_name):
        return []

    results = search_trusted_sources(db, query, include_external=False, limit=20)
    return [_candidate_from_search_result(task, item, search_backend="local_index") for item in results]


def _candidate_from_search_result(
    task: models.LocalFileIntakeTask,
    item,
    *,
    search_backend: str,
) -> models.LocalFileRecognitionCandidate:
    resource_id = item.raw.get("standard_resource_id")
    title_score = item.raw.get("title_similarity") or _similarity(task.extracted_title, item.standard_name)
    score = item.confidence_score
    advice = "create_document" if score >= 85 else "manual_review" if score >= 70 else "need_review"
    return models.LocalFileRecognitionCandidate(
        task_id=task.id,
        candidate_type="standard_resource",
        candidate_id=int(resource_id) if resource_id is not None else None,
        source_id=item.source_id,
        source_name=item.source_name,
        standard_no=item.standard_no,
        normalized_standard_no=item.normalized_standard_no,
        standard_name=item.standard_name,
        source_status=item.source_status,
        publish_date=item.publish_date,
        effective_date=item.effective_date,
        abolish_date=item.abolish_date,
        detail_url=item.detail_url,
        pdf_trial_url=item.pdf_trial_url,
        match_score=score,
        match_reason=item.match_reason or f"可信源索引命中，标题相似度 {title_score}%",
        decision_advice=advice,
        search_backend=search_backend,
    )


def _parse_source_book_id_from_detail_url(detail_url: str | None) -> str | None:
    if not detail_url:
        return None
    match = re.search(r"[?&]id=([^&]+)", detail_url, flags=re.I)
    return match.group(1) if match else None


def _system_status_from_source(source_status: str | None) -> str:
    if source_status == "废止":
        return "来源确认废止"
    if source_status == "现行":
        return "来源确认现行"
    return "待复核"


def upsert_standard_resource_from_candidate(
    db: Session,
    candidate: models.LocalFileRecognitionCandidate,
) -> int | None:
    """Persist an external/live trusted-source hit into standard_resources for evidence linking."""
    if candidate.candidate_type != "standard_resource" or not candidate.source_id:
        return None
    if candidate.candidate_id:
        return candidate.candidate_id

    source = db.get(models.TrustedSource, candidate.source_id)
    if source is None:
        return None

    source_book_id = _parse_source_book_id_from_detail_url(candidate.detail_url)
    resource = None
    if source_book_id:
        resource = db.scalars(
            select(models.StandardResource).where(
                models.StandardResource.source_id == source.id,
                models.StandardResource.source_book_id == source_book_id,
            )
        ).first()
    if resource is None and candidate.normalized_standard_no:
        resource = db.scalars(
            select(models.StandardResource)
            .where(
                models.StandardResource.source_id == source.id,
                models.StandardResource.normalized_standard_no == candidate.normalized_standard_no,
            )
            .order_by(desc(models.StandardResource.id))
        ).first()
    if resource is None and candidate.detail_url:
        resource = db.scalars(
            select(models.StandardResource).where(
                models.StandardResource.source_id == source.id,
                models.StandardResource.detail_url == candidate.detail_url,
            )
        ).first()

    number_parts = normalize_standard_no(candidate.standard_no or candidate.normalized_standard_no)
    if resource is None:
        resource = models.StandardResource(
            source_id=source.id,
            source_book_id=source_book_id,
            source_name=source.source_name,
            standard_name=candidate.standard_name or candidate.standard_no or "未命名标准",
        )
        db.add(resource)
        db.flush()

    resource.standard_no = candidate.standard_no or resource.standard_no
    resource.raw_standard_no = number_parts.raw or resource.raw_standard_no
    resource.normalized_standard_no = candidate.normalized_standard_no or number_parts.normalized or resource.normalized_standard_no
    resource.standard_prefix = number_parts.prefix or resource.standard_prefix
    resource.standard_main_no = number_parts.main_no or resource.standard_main_no
    resource.standard_year = number_parts.year or resource.standard_year
    resource.standard_revision_note = number_parts.revision_note or resource.standard_revision_note
    resource.source_status_raw = candidate.source_status
    resource.standard_name = candidate.standard_name or resource.standard_name
    resource.source_status = candidate.source_status
    resource.system_status = _system_status_from_source(candidate.source_status)
    resource.publish_date = candidate.publish_date or resource.publish_date
    resource.effective_date = candidate.effective_date or resource.effective_date
    resource.abolish_date = candidate.abolish_date or resource.abolish_date
    resource.detail_url = candidate.detail_url or resource.detail_url
    resource.pdf_trial_url = candidate.pdf_trial_url or resource.pdf_trial_url
    resource.source_confidence = source.trust_score
    resource.last_synced_at = datetime.now(UTC)
    resource.sync_status = "外网实时"
    if candidate.match_reason and not resource.summary:
        resource.summary = candidate.match_reason

    if candidate.detail_url:
        evidence_exists = db.scalars(
            select(models.StandardEvidence).where(
                models.StandardEvidence.standard_resource_id == resource.id,
                models.StandardEvidence.source_url == candidate.detail_url,
            )
        ).first()
        if evidence_exists is None:
            db.add(
                models.StandardEvidence(
                    standard_resource_id=resource.id,
                    source_name=source.source_name,
                    source_level=source.trust_level,
                    source_url=candidate.detail_url,
                    raw_status_text=candidate.source_status,
                    parsed_status=resource.system_status,
                    page_summary=candidate.match_reason,
                    evidence_note=f"{source.source_name} 外网实时搜索命中",
                )
            )

    candidate.candidate_id = resource.id
    return resource.id


def _candidate_dedupe_key(candidate: models.LocalFileRecognitionCandidate) -> str | None:
    if candidate.detail_url:
        return candidate.detail_url
    if candidate.candidate_id and candidate.candidate_type == "standard_resource":
        return f"local:{candidate.candidate_id}"
    if candidate.normalized_standard_no:
        return f"{candidate.source_id}:{candidate.normalized_standard_no}:{candidate.standard_name}"
    return None


def _intake_search_slices_for_task(task: models.LocalFileIntakeTask) -> list[TrustedSourceSearchQuery]:
    return build_intake_search_queries(
        original_file_name=task.original_file_name,
        extracted_standard_no=task.extracted_standard_no,
        normalized_standard_no=task.normalized_standard_no,
        extracted_title=task.extracted_title,
    )


def _should_auto_external_search(
    candidates: list[models.LocalFileRecognitionCandidate],
    task: models.LocalFileIntakeTask,
    *,
    has_duplicate_version: bool,
) -> bool:
    if has_duplicate_version:
        return False
    if any(item.candidate_type == "document_version" and item.match_score >= 100 for item in candidates):
        return False
    if any(item.candidate_type == "standard_resource" and item.match_score >= 85 for item in candidates):
        return False
    if any(item.candidate_type == "document" and item.match_score >= 80 for item in candidates):
        return False
    return bool(_intake_search_slices_for_task(task))


def _append_external_candidates(
    db: Session,
    task: models.LocalFileIntakeTask,
    candidates: list[models.LocalFileRecognitionCandidate],
) -> tuple[int, list[dict[str, str | int]], list[TrustedSourceSearchQuery], list[models.LocalFileRecognitionCandidate]]:
    queries = _intake_search_slices_for_task(task)
    if not queries:
        return 0, [], [], []

    errors: list[dict[str, str | int]] = []
    results = search_trusted_sources_sliced(db, queries, include_external=True, limit=20, errors=errors)
    external_results = [item for item in results if item.raw.get("search_backend") == "external"]

    existing_keys = {
        key
        for candidate in candidates
        if (key := _candidate_dedupe_key(candidate)) is not None
    }
    added_candidates: list[models.LocalFileRecognitionCandidate] = []
    for item in external_results:
        candidate = _candidate_from_search_result(task, item, search_backend="external")
        key = _candidate_dedupe_key(candidate)
        if key is not None and key in existing_keys:
            continue
        if key is not None:
            existing_keys.add(key)
        added_candidates.append(candidate)

    for candidate in added_candidates:
        db.add(candidate)

    return len(added_candidates), errors, queries, added_candidates


def _apply_decision_from_candidates(
    db: Session,
    task: models.LocalFileIntakeTask,
    candidates: list[models.LocalFileRecognitionCandidate],
) -> tuple[str, int, str, str]:
    decision, confidence, risk, reason = calculate_decision(candidates, task)
    task.decision = decision
    task.confidence_score = confidence
    task.risk_level = risk
    task.decision_reason = reason
    return decision, confidence, risk, reason


def run_external_search_for_task(db: Session, task_id: int) -> tuple[models.LocalFileIntakeTask, int, list[dict[str, str | int]]]:
    task = db.get(models.LocalFileIntakeTask, task_id)
    if task is None:
        raise ValueError("识别任务不存在")
    if task.final_action:
        raise ValueError("任务已处理，无法联网复核")

    queries = _intake_search_slices_for_task(task)
    if not queries:
        raise ValueError("无法从文件名或标题生成外网搜索切片")

    existing_candidates = list(
        db.scalars(
            select(models.LocalFileRecognitionCandidate).where(models.LocalFileRecognitionCandidate.task_id == task.id)
        )
    )
    added, errors, queries, _ = _append_external_candidates(db, task, existing_candidates)
    db.flush()

    all_candidates = list(
        db.scalars(
            select(models.LocalFileRecognitionCandidate).where(models.LocalFileRecognitionCandidate.task_id == task.id)
        )
    )
    decision, confidence, risk, reason = _apply_decision_from_candidates(db, task, all_candidates)

    _append_log(
        db,
        task.id,
        "external_search",
        "ok" if not errors else "partial",
        f"外网复核追加 {added} 条候选",
        {"added": added, "slice_count": len(queries), "errors": errors},
    )
    _append_log(
        db,
        task.id,
        "external_search_decision",
        "ok",
        reason,
        {"decision": decision, "confidence": confidence, "risk": risk, "added": added},
    )
    db.commit()
    refreshed = get_intake_task_detail(db, task_id)
    if refreshed is None:
        raise ValueError("识别任务不存在")
    return refreshed, added, errors


def calculate_decision(candidates: list[models.LocalFileRecognitionCandidate], task: models.LocalFileIntakeTask) -> tuple[str, int, str, str]:
    duplicate = next((item for item in candidates if item.candidate_type == "document_version" and item.match_score >= 100), None)
    if duplicate:
        return "duplicate_ignore", 100, "low", "已存在完全相同文件，建议忽略"

    resources = [item for item in candidates if item.candidate_type == "standard_resource"]
    documents = [item for item in candidates if item.candidate_type == "document"]

    high_resources = [item for item in resources if item.match_score >= 85]
    if len(high_resources) == 1:
        item = high_resources[0]
        title_score = _similarity(task.extracted_title, item.standard_name)
        if title_score >= 80:
            return "create_document", min(95, item.match_score), "low", f"可信源高置信匹配：{item.standard_name}"
        return "need_review", 75, "medium", "标准编号一致但标题相似度偏低，建议人工复核"

    if len(high_resources) > 1:
        return "need_review", 70, "high", "同一标准号匹配多个可信源结果，需人工选择"

    if documents:
        top = max(documents, key=lambda item: item.match_score)
        if top.match_score >= 80:
            return "link_existing", min(90, top.match_score), "medium", "疑似已有标准的不同来源或新版本，建议关联已有文件"
        return "need_review", max(60, top.match_score), "medium", "标准编号一致但标题差异较大，建议人工复核"

    if task.normalized_standard_no or task.extracted_title:
        return "need_review", 55, "medium", "未找到高置信本地或可信源匹配，建议人工复核后入库"

    return "need_review", 40, "high", "无法提取有效标准编号，仅可依据文件名模糊判断"


def analyze_local_file(db: Session, task_id: int) -> models.LocalFileIntakeTask:
    task = db.get(models.LocalFileIntakeTask, task_id)
    if task is None:
        raise ValueError("识别任务不存在")
    if task.final_action:
        raise ValueError("任务已处理，无法重复识别")

    task.recognition_status = "processing"
    db.commit()

    try:
        db.query(models.LocalFileRecognitionCandidate).filter(models.LocalFileRecognitionCandidate.task_id == task.id).delete()
        db.query(models.LocalFileIntakeLog).filter(
            models.LocalFileIntakeLog.task_id == task.id,
            models.LocalFileIntakeLog.step_name != "upload",
        ).delete()

        storage_status = check_storage_root(db, settings.storage_root)
        file_path = storage_status.root / task.temp_file_path
        if not file_path.exists():
            raise ValueError("临时文件不存在，请重新上传")

        metadata = extract_local_file_metadata(file_path, original_name=task.original_file_name, mime_type=task.mime_type)
        _apply_metadata(task, metadata)
        _append_log(db, task.id, "extract_metadata", "ok", "已提取文件名元数据", {"standard_no": task.extracted_standard_no, "title": task.extracted_title})

        candidates: list[models.LocalFileRecognitionCandidate] = []
        version_candidates = match_existing_versions(db, task)
        candidates.extend(version_candidates)
        _append_log(db, task.id, "match_versions", "ok", f"命中 {len(version_candidates)} 个相同 hash 版本")

        if not version_candidates:
            document_candidates = match_existing_documents(db, task)
            candidates.extend(document_candidates)
            _append_log(db, task.id, "match_documents", "ok", f"命中 {len(document_candidates)} 个已有标准文件")

            resource_candidates = match_standard_resources(db, task)
            candidates.extend(resource_candidates)
            _append_log(db, task.id, "match_resources", "ok", f"命中 {len(resource_candidates)} 个可信源候选")

        for candidate in candidates:
            db.add(candidate)

        auto_external_added = 0
        auto_external_errors: list[dict[str, str | int]] = []
        auto_external_slices: list[TrustedSourceSearchQuery] = []
        if _should_auto_external_search(candidates, task, has_duplicate_version=bool(version_candidates)):
            auto_external_added, auto_external_errors, auto_external_slices, added_candidates = _append_external_candidates(
                db, task, candidates
            )
            candidates.extend(added_candidates)
            _append_log(
                db,
                task.id,
                "auto_external_search",
                "ok" if not auto_external_errors else "partial",
                f"本地无高置信匹配，自动外网搜索追加 {auto_external_added} 条候选",
                {
                    "added": auto_external_added,
                    "slice_count": len(auto_external_slices),
                    "errors": auto_external_errors,
                },
            )

        decision, confidence, risk, reason = _apply_decision_from_candidates(db, task, candidates)
        task.recognition_status = "completed"
        _append_log(db, task.id, "decision", "ok", reason, {"decision": decision, "confidence": confidence, "risk": risk})
        if auto_external_added or auto_external_errors:
            _append_log(
                db,
                task.id,
                "external_search_decision",
                "ok",
                reason,
                {
                    "decision": decision,
                    "confidence": confidence,
                    "risk": risk,
                    "added": auto_external_added,
                    "auto": True,
                },
            )
        db.commit()
        db.refresh(task)
        return task
    except Exception as exc:
        task.recognition_status = "failed"
        _append_log(db, task.id, "analyze", "failed", str(exc))
        db.commit()
        raise


def _resolve_file_path(db: Session, task: models.LocalFileIntakeTask) -> Path:
    storage_status = check_storage_root(db, settings.storage_root)
    path = storage_status.root / task.temp_file_path
    if not path.exists():
        raise ValueError("临时文件不存在")
    return path


def _create_local_url_source(db: Session, task: models.LocalFileIntakeTask, *, standard_resource_id: int | None = None) -> models.UrlSource:
    remark_parts = [f"local_intake_task_id={task.id}", f"file_hash={task.file_hash}"]
    if standard_resource_id:
        remark_parts.append(f"standard_resource_id={standard_resource_id}")
    url = f"local-intake://task/{task.id}/{task.file_hash[:12]}"
    existing = db.scalars(select(models.UrlSource).where(models.UrlSource.url == url)).first()
    if existing:
        existing.remark = "；".join(remark_parts)
        return existing
    source = models.UrlSource(
        url=url,
        source_name=task.extracted_title or task.original_file_name,
        source_type="local_intake",
        remark="；".join(remark_parts),
        status=models.SourceStatus.normal.value,
    )
    db.add(source)
    db.flush()
    return source


def _archive_task_file(db: Session, task: models.LocalFileIntakeTask, source: models.UrlSource) -> tuple[Path, str]:
    storage_status = check_storage_root(db, settings.storage_root)
    src = _resolve_file_path(db, task)
    now = datetime.now(UTC)
    relative = f"url-sources/{source.id}/{now.strftime('%Y%m%d')}/{now.strftime('%H%M%S')}_{Path(task.original_file_name).name}"
    target = storage_status.root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    return target, relative_storage_path(storage_status.root, target)


def _apply_standard_fields(document: models.Document, task: models.LocalFileIntakeTask) -> None:
    parts = normalize_standard_no(task.extracted_standard_no)
    document.title = task.extracted_title or task.original_file_name
    document.standard_no = parts.raw or task.extracted_standard_no
    document.raw_standard_no = parts.raw
    document.normalized_standard_no = parts.normalized or task.normalized_standard_no
    document.standard_prefix = parts.prefix
    document.standard_main_no = parts.main_no
    document.standard_year = parts.year
    document.standard_revision_note = parts.revision_note
    document.doc_type = task.file_type or doc_type(task.original_file_name, task.mime_type)
    document.valid_status = models.ValidStatus.pending.value
    document.review_status = models.ReviewStatus.pending.value
    document.metadata_status = "本地文件识别"


def confirm_intake_decision(
    db: Session,
    task_id: int,
    *,
    action: str,
    document_id: int | None = None,
    standard_resource_id: int | None = None,
    candidate_id: int | None = None,
    reviewed_by: str | None = None,
    remark: str | None = None,
) -> dict:
    task = db.get(models.LocalFileIntakeTask, task_id)
    if task is None:
        raise ValueError("识别任务不存在")

    action = (action or "").strip().lower()
    allowed = {"ignore", "link_existing", "new_version", "create_document", "mark_review"}
    if action not in allowed:
        raise ValueError(f"不支持的处理动作：{action}")

    if action == "mark_review":
        task.final_action = "mark_review"
        task.recognition_status = "reviewed"
        task.reviewed_by = reviewed_by
        task.reviewed_at = datetime.now(UTC)
        task.decision = "need_review"
        if remark:
            task.decision_reason = remark
        _append_log(db, task.id, "confirm", "ok", "已标记待复核")
        db.commit()
        db.refresh(task)
        return {"ok": True, "action": action, "task_id": task.id}

    if action == "ignore":
        task.final_action = "ignore"
        task.recognition_status = "reviewed"
        task.reviewed_by = reviewed_by
        task.reviewed_at = datetime.now(UTC)
        task.decision = "duplicate_ignore"
        _append_log(db, task.id, "confirm", "ok", remark or "用户确认忽略")
        _cleanup_temp_file(db, task)
        db.commit()
        db.refresh(task)
        return {"ok": True, "action": action, "task_id": task.id}

    if not get_bool_setting(db, "ingest_enabled", default=False):
        raise ValueError("文件入库开关已关闭（ingest_enabled=false），无法正式入库")

    candidate = db.get(models.LocalFileRecognitionCandidate, candidate_id) if candidate_id else None
    if candidate and candidate.task_id != task.id:
        raise ValueError("候选记录与任务不匹配")
    if candidate:
        if candidate.candidate_type == "document":
            document_id = document_id or candidate.candidate_id
        elif candidate.candidate_type == "document_version":
            version = db.get(models.DocumentVersion, candidate.candidate_id)
            if version is not None:
                document_id = document_id or version.document_id
        elif candidate.candidate_type == "standard_resource":
            standard_resource_id = standard_resource_id or candidate.candidate_id
            if standard_resource_id is None:
                standard_resource_id = upsert_standard_resource_from_candidate(db, candidate)

    source = _create_local_url_source(db, task, standard_resource_id=standard_resource_id)
    _, storage_path = _archive_task_file(db, task, source)

    if action == "create_document":
        document = models.Document()
        _apply_standard_fields(document, task)
        db.add(document)
        db.flush()
        document_id = document.id
    elif action in {"link_existing", "new_version"}:
        if not document_id:
            raise ValueError("关联已有文件或新增版本时必须指定 document_id")
        document = db.get(models.Document, document_id)
        if document is None:
            raise ValueError("指定的 Document 不存在")
    else:
        raise ValueError(f"不支持的处理动作：{action}")

    existing_same_hash = db.scalars(
        select(models.DocumentVersion)
        .where(models.DocumentVersion.document_id == document.id, models.DocumentVersion.file_hash == task.file_hash)
        .order_by(desc(models.DocumentVersion.id))
    ).first()
    if existing_same_hash:
        task.final_action = action
        task.recognition_status = "reviewed"
        task.reviewed_by = reviewed_by
        task.reviewed_at = datetime.now(UTC)
        task.linked_document_id = document.id
        task.linked_version_id = existing_same_hash.id
        task.decision = "duplicate_ignore"
        task.decision_reason = "确认时发现该 Document 已存在相同 hash 版本"
        _append_log(db, task.id, "confirm", "ok", task.decision_reason)
        _cleanup_temp_file(db, task)
        db.commit()
        db.refresh(task)
        return {
            "ok": True,
            "action": "duplicate",
            "task_id": task.id,
            "document_id": document.id,
            "version_id": existing_same_hash.id,
        }

    db.query(models.DocumentVersion).filter(
        models.DocumentVersion.document_id == document.id,
        models.DocumentVersion.is_current.is_(True),
    ).update({"is_current": False})

    version = models.DocumentVersion(
        document_id=document.id,
        url_source_id=source.id,
        version_no=f"v{len(document.versions) + 1}",
        file_name=task.original_file_name,
        original_file_name=task.original_file_name,
        file_path=storage_path,
        file_hash=task.file_hash,
        file_size=task.file_size,
        content_hash=task.file_hash,
        change_type=models.ChangeType.created.value if action == "create_document" else models.ChangeType.updated.value,
        is_current=True,
        remark=remark,
    )
    db.add(version)
    db.flush()
    document.current_version_id = version.id

    linked = 0
    if standard_resource_id:
        source.remark = f"{source.remark or ''}；standard_resource_id={standard_resource_id}".strip("；")
        resource = db.get(models.StandardResource, standard_resource_id)
        if resource is not None:
            linked = link_archived_document_to_resources(db, document=document, source=source)
            calibrate_resource_status(db, resource)
    elif task.normalized_standard_no or task.extracted_standard_no:
        linked = link_archived_document_to_resources(db, document=document, source=source)

    task.final_action = action
    task.recognition_status = "reviewed"
    task.reviewed_by = reviewed_by
    task.reviewed_at = datetime.now(UTC)
    task.linked_document_id = document.id
    task.linked_version_id = version.id
    _append_log(
        db,
        task.id,
        "confirm",
        "ok",
        remark or f"已执行 {action}",
        {"document_id": document.id, "version_id": version.id, "linked_resources": linked},
    )
    _cleanup_temp_file(db, task)
    db.commit()
    db.refresh(task)
    return {
        "ok": True,
        "action": action,
        "task_id": task.id,
        "document_id": document.id,
        "version_id": version.id,
        "linked_resources": linked,
    }


def _cleanup_temp_file(db: Session, task: models.LocalFileIntakeTask) -> None:
    storage_status = check_storage_root(db, settings.storage_root)
    path = storage_status.root / task.temp_file_path
    if path.exists():
        path.unlink(missing_ok=True)
    parent = path.parent
    if parent.exists() and parent.name.isdigit() and not any(parent.iterdir()):
        parent.rmdir()


def delete_intake_task(db: Session, task_id: int) -> None:
    task = db.get(models.LocalFileIntakeTask, task_id)
    if task is None:
        raise ValueError("识别任务不存在")
    if task.linked_version_id:
        raise ValueError("任务已入库，不能删除")
    _cleanup_temp_file(db, task)
    db.delete(task)
    db.commit()


def list_intake_tasks_page(
    db: Session,
    *,
    page_size: int = 50,
    cursor: int | None = None,
    q: str | None = None,
    recognition_status: str | None = None,
    decision: str | None = None,
) -> tuple[list[models.LocalFileIntakeTask], int, int | None, bool]:
    statement = select(models.LocalFileIntakeTask)
    if q:
        like = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                models.LocalFileIntakeTask.original_file_name.ilike(like),
                models.LocalFileIntakeTask.extracted_standard_no.ilike(like),
                models.LocalFileIntakeTask.extracted_title.ilike(like),
            )
        )
    if recognition_status:
        statement = statement.where(models.LocalFileIntakeTask.recognition_status == recognition_status)
    if decision:
        statement = statement.where(models.LocalFileIntakeTask.decision == decision)
    if cursor:
        statement = statement.where(models.LocalFileIntakeTask.id < cursor)

    count_statement = select(func.count()).select_from(statement.subquery())
    total = db.scalar(count_statement) or 0
    page_size = min(max(page_size, 1), 200)
    items = list(db.scalars(statement.order_by(desc(models.LocalFileIntakeTask.id)).limit(page_size + 1)))
    has_more = len(items) > page_size
    if has_more:
        items = items[:page_size]
    next_cursor = items[-1].id if has_more and items else None
    return items, total, next_cursor, has_more


def get_intake_task_detail(db: Session, task_id: int) -> models.LocalFileIntakeTask | None:
    task = db.get(models.LocalFileIntakeTask, task_id)
    if task is None:
        return None
    task.candidates.sort(key=lambda item: item.match_score, reverse=True)
    task.logs.sort(key=lambda item: item.created_at)
    return task
