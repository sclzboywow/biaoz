"""URL 来源治理操作：单条/批量状态变更与重新画像。"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app import models
from app.governance_service import log_process_audit, profile_url_sources_batch
from app.source_governance import (
    GOV_BLACKLIST,
    GOV_CLUE_ONLY,
    GOV_HIGH_PRIORITY,
    GOV_NEED_OCR,
    GOV_PAUSED,
    profile_url_source_row,
)

ACTION_MAP = {
    "reprofile": None,
    "mark_clue": GOV_CLUE_ONLY,
    "blacklist_candidate": GOV_BLACKLIST,
    "raise_priority": GOV_HIGH_PRIORITY,
    "to_ocr_queue": GOV_NEED_OCR,
    "pause_collect": GOV_PAUSED,
}


def apply_url_governance_action(db: Session, source_id: int, action: str) -> models.UrlSource:
    if action not in ACTION_MAP:
        raise ValueError(f"unsupported action: {action}")
    source = db.get(models.UrlSource, source_id)
    if source is None:
        raise ValueError("url source not found")

    if action == "reprofile":
        row = profile_url_source_row(source.url)
        source.host = row["host"]
        source.url_type = row["url_type"]
        source.file_ext = row["file_ext"]
        source.is_official_domain = row["is_official_domain"]
        source.is_cloud_drive = row["is_cloud_drive"]
        source.is_probable_pdf = row["is_probable_pdf"]
        source.is_probable_detail_page = row["is_probable_detail_page"]
        source.source_quality_score = row["source_quality_score"]
        source.governance_status = row["governance_status"]
        source.duplicate_group_key = row["duplicate_group_key"]
    else:
        source.governance_status = ACTION_MAP[action]

    log_process_audit(
        db,
        process_name="url_governance",
        action=f"url_action_{action}",
        target_type="url_source",
        target_id=source.id,
        message=source.governance_status,
        detail={"action": action},
    )
    db.commit()
    db.refresh(source)
    return source


def batch_url_governance_actions(db: Session, source_ids: list[int], action: str) -> dict:
    if action not in ACTION_MAP:
        raise ValueError(f"unsupported action: {action}")
    if not source_ids:
        return {"updated": 0, "action": action}

    if action == "reprofile":
        updated = 0
        for source_id in source_ids[:500]:
            try:
                apply_url_governance_action(db, source_id, action)
                updated += 1
            except ValueError:
                continue
        return {"updated": updated, "action": action}

    updated = 0
    status = ACTION_MAP[action]
    for source_id in source_ids[:500]:
        source = db.get(models.UrlSource, source_id)
        if source is None:
            continue
        source.governance_status = status
        updated += 1
        log_process_audit(
            db,
            process_name="url_governance",
            action=f"url_batch_{action}",
            target_type="url_source",
            target_id=source.id,
            message=status,
            detail={"action": action},
        )
    db.commit()
    return {"updated": updated, "action": action}


def batch_profile_url_sources(db: Session, source_ids: list[int], *, dry_run: bool = False) -> dict:
    if not source_ids:
        return {"total": 0, "profiled": 0}
    total = 0
    profiled = 0
    for source_id in source_ids[:200]:
        source = db.get(models.UrlSource, source_id)
        if source is None:
            continue
        total += 1
        if not dry_run:
            apply_url_governance_action(db, source_id, "reprofile")
        profiled += 1
    log_process_audit(
        db,
        process_name="url_governance",
        action="batch_reprofile",
        message=f"profiled={profiled}",
        detail={"source_ids": source_ids[:200], "dry_run": dry_run},
    )
    if dry_run:
        db.rollback()
    return {"total": total, "profiled": profiled, "dry_run": dry_run}
