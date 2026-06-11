"""治理自动化：入库资格过滤、告警自动消警。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app import models
from app.alerts import mark_alert_auto_handled
from app.governance_decision_engine import (
    DECISION_AUTO_REJECTED,
    DECISION_NEED_REVIEW,
)

BLOCKED_SYSTEM_STATUSES = frozenset({"已拒绝", "黑名单", "黑名单候选"})
ABOLISHED_SOURCE_MARKERS = ("废止", "作废", "停止实施", "被替代")
ABOLISHED_LOCAL_STATUSES = frozenset({"废止", "来源确认废止", "已废止", "确认废止", "疑似被替代"})
SOURCE_STATUS_TO_DOCUMENT_STATUS = {
    "现行": "来源确认现行",
    "废止": "来源确认废止",
    "被替代": "疑似被替代",
    "即将实施": "待复核",
    "未知": "待复核",
}


def standard_resource_ingest_eligibility_clause() -> ColumnElement[bool]:
    """SQLAlchemy 条件：允许进入文件 batch 候选。"""
    return and_(
        or_(
            models.StandardResource.auto_decision.is_(None),
            models.StandardResource.auto_decision.notin_(
                [DECISION_NEED_REVIEW, DECISION_AUTO_REJECTED]
            ),
        ),
        or_(
            models.StandardResource.system_status.is_(None),
            models.StandardResource.system_status.notin_(tuple(BLOCKED_SYSTEM_STATUSES)),
        ),
    )


def is_standard_resource_eligible_for_ingest(resource: models.StandardResource) -> bool:
    decision = (resource.auto_decision or "").strip().upper()
    if decision in {DECISION_NEED_REVIEW, DECISION_AUTO_REJECTED}:
        return False
    system_status = (resource.system_status or "").strip()
    if system_status in BLOCKED_SYSTEM_STATUSES:
        return False
    source_status = (resource.source_status or "").strip()
    if any(marker in source_status for marker in ABOLISHED_SOURCE_MARKERS):
        if decision in {DECISION_NEED_REVIEW, DECISION_AUTO_REJECTED}:
            return False
    return True


def _abolished_status(value: str | None) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    return any(marker in text for marker in ABOLISHED_SOURCE_MARKERS) or text in ABOLISHED_LOCAL_STATUSES


def _document_status_is_aligned(document: models.Document) -> bool:
    source_status = (document.source_status or "未知").strip()
    suggested_status = SOURCE_STATUS_TO_DOCUMENT_STATUS.get(source_status, "待复核")
    system_status = (document.system_status or document.valid_status or "").strip()
    if system_status == suggested_status:
        return True
    if _abolished_status(system_status) and _abolished_status(source_status):
        return True
    if system_status in {"来源确认现行", "现行"} and source_status in {"现行", "未知", "即将实施"}:
        return True
    if system_status in {"来源确认废止", "废止", "疑似被替代"} and source_status in {"废止", "被替代"}:
        return True
    return False


def auto_resolve_status_calibration_alerts(
    db: Session,
    *,
    resource: models.StandardResource,
    document: models.Document,
    old_status: str | None,
    suggested_status: str,
    is_conflict: bool,
) -> int:
    """状态已对齐或双方均为废止类状态时，自动消警。"""
    resolved = 0
    dedupe_prefix = f"status-calibration:{resource.id}:{document.id}:"
    alerts = list(
        db.scalars(
            select(models.Alert).where(
                models.Alert.status == models.AlertStatus.pending.value,
                models.Alert.document_id == document.id,
                models.Alert.dedupe_key.like(f"{dedupe_prefix}%"),
            )
        ).all()
    )
    if not alerts:
        return 0

    both_abolished = _abolished_status(old_status) and _abolished_status(suggested_status)
    aligned = (old_status or "") == suggested_status or not is_conflict
    trusted_aligned = (
        resource.source_confidence is not None
        and resource.source_confidence >= 70
        and suggested_status in {"来源确认现行", "来源确认废止", "现行", "废止"}
        and not is_conflict
    )

    if both_abolished or aligned or trusted_aligned:
        for alert in alerts:
            mark_alert_auto_handled(alert)
            resolved += 1
    return resolved


def auto_resolve_ingest_success_alerts(
    db: Session,
    *,
    document: models.Document,
    source: models.UrlSource,
    change_type: str,
) -> int:
    """文件成功归档后，关闭同文档的信息性/已解决告警。"""
    resolved = 0
    pending = list(
        db.scalars(
            select(models.Alert).where(
                models.Alert.status == models.AlertStatus.pending.value,
                or_(
                    models.Alert.document_id == document.id,
                    models.Alert.url_source_id == source.id,
                ),
            )
        ).all()
    )
    for alert in pending:
        alert_type = (alert.alert_type or "").strip()
        if alert_type in {"新增文件", "文件更新"}:
            mark_alert_auto_handled(alert)
            resolved += 1
            continue
        if change_type in {models.ChangeType.created.value, models.ChangeType.updated.value}:
            if alert_type in {"可信源状态冲突", "可信源废止提醒"} and _abolished_status(document.system_status):
                mark_alert_auto_handled(alert)
                resolved += 1
    return resolved


def auto_resolve_governance_decision_alerts(
    db: Session,
    *,
    resource: models.StandardResource,
    decision: str,
) -> int:
    """自动决策完成后，关闭该资源上的治理类 pending 告警。"""
    if decision in {DECISION_NEED_REVIEW, DECISION_AUTO_REJECTED}:
        return 0
    resolved = 0
    prefix = f"governance:{resource.id}:"
    alerts = list(
        db.scalars(
            select(models.Alert).where(
                models.Alert.status == models.AlertStatus.pending.value,
                models.Alert.dedupe_key.like(f"{prefix}%"),
            )
        ).all()
    )
    for alert in alerts:
        mark_alert_auto_handled(alert)
        resolved += 1
    return resolved


def auto_resolve_bulk_informational_alerts(db: Session, *, limit: int = 5000) -> int:
    """批量关闭已归档文档上的「新增文件」类 pending 告警。"""
    limit = max(1, min(limit, 20000))
    rows = list(
        db.scalars(
            select(models.Alert)
            .where(
                models.Alert.status == models.AlertStatus.pending.value,
                models.Alert.alert_type.in_(("新增文件", "文件更新")),
                models.Alert.document_id.isnot(None),
            )
            .order_by(models.Alert.id.asc())
            .limit(limit)
        ).all()
    )
    resolved = 0
    for alert in rows:
        if alert.document_id is None:
            continue
        version = db.scalars(
            select(models.DocumentVersion)
            .where(
                models.DocumentVersion.document_id == alert.document_id,
                models.DocumentVersion.is_current.is_(True),
            )
            .limit(1)
        ).first()
        if version is not None:
            mark_alert_auto_handled(alert)
            resolved += 1
    return resolved


def sweep_auto_resolvable_alerts(db: Session, *, limit: int = 2000) -> dict[str, int]:
    """治理循环末尾：批量消减可自动关闭的告警。"""
    batch_limit = max(1, min(limit, 20000))
    informational = auto_resolve_bulk_informational_alerts(db, limit=batch_limit)
    status_aligned = _auto_resolve_status_conflict_alerts(db, limit=batch_limit)
    operational = _auto_resolve_stale_operational_alerts(db, limit=batch_limit)
    governance = _auto_resolve_decided_governance_alerts(db, limit=batch_limit)
    if informational or status_aligned or operational or governance:
        db.flush()
    return {
        "informational_resolved": informational,
        "abolished_aligned_resolved": status_aligned,
        "operational_resolved": operational,
        "governance_resolved": governance,
    }


def sweep_all_auto_resolvable_alerts(
    db: Session,
    *,
    batch_limit: int = 20000,
    max_rounds: int = 100,
    force_remaining: bool = False,
) -> dict[str, int]:
    """循环清扫直到本轮无法再自动关闭任何 pending 告警。"""
    totals = {
        "informational_resolved": 0,
        "abolished_aligned_resolved": 0,
        "operational_resolved": 0,
        "governance_resolved": 0,
        "force_resolved": 0,
        "rounds": 0,
    }
    for _ in range(max_rounds):
        stats = sweep_auto_resolvable_alerts(db, limit=batch_limit)
        totals["rounds"] += 1
        progressed = False
        for key in ("informational_resolved", "abolished_aligned_resolved", "operational_resolved", "governance_resolved"):
            count = int(stats.get(key) or 0)
            totals[key] += count
            if count > 0:
                progressed = True
        if not progressed:
            break
    if force_remaining:
        totals["force_resolved"] = _force_resolve_remaining_pending_alerts(db)
    return totals


def _force_resolve_remaining_pending_alerts(db: Session) -> int:
    alerts = list(
        db.scalars(
            select(models.Alert).where(models.Alert.status == models.AlertStatus.pending.value)
        ).all()
    )
    for alert in alerts:
        mark_alert_auto_handled(alert)
    if alerts:
        db.flush()
    return len(alerts)


def _auto_resolve_status_conflict_alerts(db: Session, *, limit: int) -> int:
    resolved = 0
    alerts = list(
        db.scalars(
            select(models.Alert)
            .where(
                models.Alert.status == models.AlertStatus.pending.value,
                models.Alert.alert_type.in_(("可信源状态冲突", "可信源废止提醒")),
                models.Alert.document_id.isnot(None),
            )
            .order_by(models.Alert.id.asc())
            .limit(limit)
        ).all()
    )
    for alert in alerts:
        document = db.get(models.Document, alert.document_id) if alert.document_id else None
        if document is None:
            continue
        if _document_status_is_aligned(document):
            mark_alert_auto_handled(alert)
            resolved += 1
    return resolved


def _auto_resolve_stale_operational_alerts(db: Session, *, limit: int) -> int:
    from pathlib import Path

    from app.settings_store import get_bool_setting, get_setting
    from app.storage import check_storage_root, configured_storage_root

    resolved = 0
    if get_bool_setting(db, "ingest_enabled", default=False):
        alerts = list(
            db.scalars(
                select(models.Alert)
                .where(
                    models.Alert.status == models.AlertStatus.pending.value,
                    models.Alert.alert_type == "入库暂停",
                )
                .order_by(models.Alert.id.asc())
                .limit(limit)
            ).all()
        )
        for alert in alerts:
            mark_alert_auto_handled(alert)
            resolved += 1

    fallback = Path(get_setting(db, "storage_root", "G:/data/standard-docs") or "G:/data/standard-docs")
    storage_status = check_storage_root(db, configured_storage_root(db, fallback))
    if storage_status.available:
        remaining = max(0, limit - resolved)
        if remaining > 0:
            alerts = list(
                db.scalars(
                    select(models.Alert)
                    .where(
                        models.Alert.status == models.AlertStatus.pending.value,
                        models.Alert.alert_type == "存储目录不可用",
                    )
                    .order_by(models.Alert.id.asc())
                    .limit(remaining)
                ).all()
            )
            for alert in alerts:
                mark_alert_auto_handled(alert)
                resolved += 1
    return resolved


def _auto_resolve_decided_governance_alerts(db: Session, *, limit: int) -> int:
    resolved = 0
    alerts = list(
        db.scalars(
            select(models.Alert)
            .where(
                models.Alert.status == models.AlertStatus.pending.value,
                models.Alert.dedupe_key.like("governance:%"),
            )
            .order_by(models.Alert.id.asc())
            .limit(limit)
        ).all()
    )
    for alert in alerts:
        dedupe_key = alert.dedupe_key or ""
        parts = dedupe_key.split(":")
        if len(parts) < 2 or not parts[1].isdigit():
            continue
        resource = db.get(models.StandardResource, int(parts[1]))
        if resource is None:
            continue
        decision = (resource.auto_decision or "").strip().upper()
        if decision and decision not in {DECISION_NEED_REVIEW, DECISION_AUTO_REJECTED}:
            mark_alert_auto_handled(alert)
            resolved += 1
    return resolved
