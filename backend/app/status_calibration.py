from __future__ import annotations

from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models


SOURCE_STATUS_TO_DOCUMENT_STATUS = {
    "现行": "来源确认现行",
    "废止": "来源确认废止",
}


def _similarity(left: str | None, right: str | None) -> int:
    return int(SequenceMatcher(None, left or "", right or "").ratio() * 100)


def match_resource_to_documents(db: Session, resource: models.StandardResource) -> list[models.StandardFileMatch]:
    if not resource.standard_no:
        return []

    documents = list(
        db.scalars(
            select(models.Document).where(models.Document.standard_no == resource.standard_no)
        )
    )
    matches: list[models.StandardFileMatch] = []
    for document in documents:
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
            match_type="标准编号完全一致",
            match_score=100 if score >= 60 else score,
            match_reason=f"标准编号一致：{resource.standard_no}",
            status="自动确认" if score >= 60 else "待确认",
        )
        db.add(match)
        db.flush()
        matches.append(match)

    resource.matched_document_count = len(matches)
    return matches


def calibrate_resource_status(db: Session, resource: models.StandardResource) -> dict[str, int]:
    matches = match_resource_to_documents(db, resource)
    created_logs = 0
    created_alerts = 0

    for match in matches:
        document = db.get(models.Document, match.document_id)
        if document is None:
            continue

        source_status = resource.source_status or ""
        suggested_status = SOURCE_STATUS_TO_DOCUMENT_STATUS.get(source_status)
        if not suggested_status:
            continue

        old_status = document.valid_status
        is_conflict = old_status not in {suggested_status, "待确认", None}
        sync_action = "生成复核任务" if is_conflict else "来源状态同步"
        sync_reason = (
            f"可信源 {resource.source_name or '国标电子书库'} 显示状态为 {source_status}"
            + (f"，废止日期 {resource.abolish_date}" if resource.abolish_date else "")
        )

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

        if is_conflict or source_status == "废止":
            db.add(
                models.Alert(
                    document_id=document.id,
                    url_source_id=None,
                    alert_type="可信源状态冲突" if is_conflict else "可信源废止提醒",
                    alert_level=models.AlertLevel.high.value,
                    message=(
                        f"{document.title}：本地状态 {old_status}，可信源状态 {source_status}。"
                        f"证据：{resource.detail_url or ''}"
                    ),
                    status=models.AlertStatus.pending.value,
                )
            )
            created_alerts += 1
        elif document.review_status != models.ReviewStatus.confirmed.value:
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

    logs = list(
        db.scalars(
            select(models.StandardChangeLog).where(
                models.StandardChangeLog.standard_resource_id == resource.id,
                models.StandardChangeLog.document_id.is_(None),
            )
        )
    )
    updated = 0
    for log in logs:
        for match in matches:
            log.document_id = match.document_id
            log.document_version_id = match.document_version_id
            log.evidence_summary = f"可信源字段 {log.field_name} 变化，详情页：{log.source_url or resource.detail_url or ''}"
            updated += 1
            break
    return updated
