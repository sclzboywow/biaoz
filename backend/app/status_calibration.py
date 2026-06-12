from __future__ import annotations

import re
from difflib import SequenceMatcher

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app import models
from app.alerts import upsert_pending_alert
from app.governance_automation import auto_resolve_status_calibration_alerts
from app.standard_number import normalize_standard_no


SOURCE_STATUS_TO_DOCUMENT_STATUS = {
    "现行": "来源确认现行",
    "废止": "来源确认废止",
    "被替代": "疑似被替代",
    "即将实施": "待复核",
    "未知": "待复核",
    "鐜拌": "来源确认现行",
    "搴熸": "来源确认废止",
}

CHANGE_FIELD_LABELS = {
    "standard_no": "标准编号",
    "standard_name": "标准名称",
    "source_status": "可信源状态",
    "publish_date": "发布日期",
    "effective_date": "实施日期",
    "abolish_date": "废止日期",
    "change_info": "变更信息",
}


def _similarity(left: str | None, right: str | None) -> int:
    return int(SequenceMatcher(None, left or "", right or "").ratio() * 100)


def _resource_number(resource: models.StandardResource) -> str | None:
    return resource.normalized_standard_no or normalize_standard_no(resource.standard_no).normalized


def _document_number(document: models.Document) -> str | None:
    normalized = document.normalized_standard_no or normalize_standard_no(document.standard_no).normalized
    if normalized and not document.normalized_standard_no:
        parts = normalize_standard_no(document.standard_no)
        document.raw_standard_no = parts.raw
        document.normalized_standard_no = parts.normalized
        document.standard_prefix = parts.prefix
        document.standard_main_no = parts.main_no
        document.standard_year = parts.year
        document.standard_revision_note = parts.revision_note
    return normalized


def match_resource_to_documents(db: Session, resource: models.StandardResource) -> list[models.StandardFileMatch]:
    resource_no = _resource_number(resource)
    if not resource_no:
        return []

    documents = list(
        db.scalars(
            select(models.Document).where(
                or_(
                    models.Document.normalized_standard_no == resource_no,
                    models.Document.standard_no == resource.standard_no,
                )
            )
        )
    )

    matches: list[models.StandardFileMatch] = []
    for document in documents:
        document_no = _document_number(document)
        if document_no != resource_no and document.standard_no != resource.standard_no:
            continue

        existing = db.scalars(
            select(models.StandardFileMatch).where(
                models.StandardFileMatch.standard_resource_id == resource.id,
                models.StandardFileMatch.document_id == document.id,
            )
        ).first()
        if existing:
            matches.append(existing)
            continue

        score = _similarity(document.title, resource.standard_name)
        match = models.StandardFileMatch(
            standard_resource_id=resource.id,
            document_id=document.id,
            document_version_id=document.current_version_id,
            match_type="规范化编号一致",
            match_score=100 if score >= 60 else score,
            match_reason=f"本地文件与可信源编号规范化后均为：{resource_no}",
            status="自动确认" if score >= 60 else "待确认",
        )
        db.add(match)
        db.flush()
        matches.append(match)

    resource.matched_document_count = len(matches)
    return matches


def extract_standard_resource_id_from_remark(remark: str | None) -> int | None:
    text = remark or ""
    match = re.search(r"standard_resource_id\s*=\s*(\d+)", text, flags=re.I)
    if match:
        return int(match.group(1))
    return None


def link_archived_document_to_resources(db: Session, *, document: models.Document, source: models.UrlSource) -> int:
    """After a file is archived, link Document <-> StandardResource and refresh matched_document_count."""
    linked_resources: list[models.StandardResource] = []
    resource_id = extract_standard_resource_id_from_remark(source.remark)
    if resource_id:
        resource = db.get(models.StandardResource, resource_id)
        if resource is not None:
            linked_resources.append(resource)

    standard_no = (_document_number(document) or document.standard_no or "").strip()
    if standard_no:
        for resource in db.scalars(
            select(models.StandardResource).where(
                or_(
                    models.StandardResource.standard_no == standard_no,
                    models.StandardResource.normalized_standard_no == standard_no,
                )
            )
        ):
            if resource not in linked_resources:
                linked_resources.append(resource)

    linked = 0
    for resource in linked_resources:
        calibration = calibrate_resource_status(db, resource)
        if calibration["matches"]:
            linked += 1
    return linked


def calibrate_resource_status(db: Session, resource: models.StandardResource) -> dict[str, int]:
    matches = match_resource_to_documents(db, resource)
    created_logs = 0
    created_alerts = 0

    for match in matches:
        document = db.get(models.Document, match.document_id)
        if document is None:
            continue

        source_status = resource.source_status or "未知"
        suggested_status = SOURCE_STATUS_TO_DOCUMENT_STATUS.get(source_status)
        if not suggested_status:
            suggested_status = "待复核"

        old_status = document.system_status or document.valid_status
        document.source_status = source_status
        document.system_status = suggested_status

        is_conflict = old_status not in {suggested_status, "待确认", "寰呯‘璁?", None}
        sync_action = "生成复核任务" if is_conflict else "来源状态同步"
        sync_reason = (
            f"可信源 {resource.source_name or '国标电子书库'} 显示状态为 {source_status}"
            + (f"，废止日期 {resource.abolish_date}" if resource.abolish_date else "")
            + (f"，详情页 {resource.detail_url}" if resource.detail_url else "")
        )

        latest_sync_log = db.scalars(
            select(models.SourceStatusSyncLog)
            .where(models.SourceStatusSyncLog.standard_resource_id == resource.id)
            .where(models.SourceStatusSyncLog.document_id == document.id)
            .order_by(desc(models.SourceStatusSyncLog.id))
            .limit(1)
        ).first()
        status_changed = old_status != suggested_status
        duplicate_latest_log = (
            latest_sync_log is not None
            and latest_sync_log.old_status == old_status
            and latest_sync_log.new_status == suggested_status
            and latest_sync_log.sync_action == sync_action
            and latest_sync_log.sync_reason == sync_reason
        )
        if status_changed and not duplicate_latest_log:
            db.add(
                models.SourceStatusSyncLog(
                    standard_resource_id=resource.id,
                    document_id=document.id,
                    old_status=old_status,
                    new_status=suggested_status,
                    sync_action=sync_action,
                    sync_reason=sync_reason,
                )
            )
            created_logs += 1

        evidence_exists = db.scalars(
            select(models.StandardEvidence).where(
                models.StandardEvidence.standard_resource_id == resource.id,
                models.StandardEvidence.document_id == document.id,
                models.StandardEvidence.raw_status_text == source_status,
                models.StandardEvidence.page_html_hash == resource.detail_hash,
            )
        ).first()
        if evidence_exists is None:
            db.add(
                models.StandardEvidence(
                    standard_resource_id=resource.id,
                    document_id=document.id,
                    source_name=resource.source_name,
                    source_level="A",
                    source_url=resource.detail_url,
                    raw_status_text=source_status,
                    parsed_status=suggested_status,
                    page_summary=resource.summary,
                    page_html_hash=resource.detail_hash,
                    evidence_note=sync_reason,
                )
            )

        if (is_conflict or suggested_status in {"来源确认废止", "疑似被替代"}) and is_conflict:
            upsert_pending_alert(
                db,
                alert_type="可信源状态冲突" if is_conflict else "可信源废止提醒",
                alert_level=models.AlertLevel.high.value,
                risk_level="high",
                message=(
                    f"{document.title}：本地状态 {old_status}，可信源状态 {source_status}。"
                    f"证据：{resource.detail_url or ''}"
                ),
                dedupe_key=f"status-calibration:{resource.id}:{document.id}:{source_status}",
                document_id=document.id,
            )
            created_alerts += 1
        elif suggested_status in {"来源确认废止", "疑似被替代"} and not is_conflict:
            pass
        auto_resolve_status_calibration_alerts(
            db,
            resource=resource,
            document=document,
            old_status=old_status,
            suggested_status=suggested_status,
            is_conflict=is_conflict,
        )
        if document.manual_status is None and document.review_status != models.ReviewStatus.confirmed.value:
            document.valid_status = suggested_status

    return {"matches": len(matches), "sync_logs": created_logs, "alerts": created_alerts}


def attach_change_logs_to_documents(db: Session, resource: models.StandardResource) -> int:
    matches = list(
        db.scalars(
            select(models.StandardFileMatch).where(
                models.StandardFileMatch.standard_resource_id == resource.id
            )
        )
    )
    if not matches:
        return 0

    logs = list(db.scalars(select(models.StandardChangeLog).where(models.StandardChangeLog.standard_resource_id == resource.id)))
    updated = 0
    match = matches[0]
    for log in logs:
        changed = False
        if log.document_id != match.document_id:
            log.document_id = match.document_id
            changed = True
        if log.document_version_id != match.document_version_id:
            log.document_version_id = match.document_version_id
            changed = True
        field_label = CHANGE_FIELD_LABELS.get(log.field_name, log.field_name)
        summary = f"可信源{field_label}发生变化，已关联本地文件版本 {match.document_version_id or '-'}"
        if log.evidence_summary != summary:
            log.evidence_summary = summary
            changed = True
        if log.handled_status != "已处理":
            log.handled_status = "已处理"
            changed = True
        if changed:
            updated += 1
    return updated
