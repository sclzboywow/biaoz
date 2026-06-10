from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models

SYSTEM_ALERT_HANDLER = "system-auto"
PROCESS_AUDIT_ONLY = "audit-only"


def mark_alert_auto_handled(alert: models.Alert, handled_by: str = SYSTEM_ALERT_HANDLER) -> models.Alert:
    alert.status = models.AlertStatus.handled.value
    alert.handled_at = alert.handled_at or datetime.now(UTC)
    alert.handled_by = alert.handled_by or handled_by
    return alert


def build_alert_dedupe_key(*parts: str | int | None) -> str:
    raw = "|".join(str(part or "") for part in parts if part is not None)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def upsert_pending_alert(
    db: Session,
    *,
    alert_type: str,
    message: str,
    alert_level: str = models.AlertLevel.high.value,
    risk_level: str = "high",
    dedupe_key: str | None = None,
    document_id: int | None = None,
    url_source_id: int | None = None,
) -> models.Alert:
    now = datetime.now(UTC)
    key = dedupe_key or build_alert_dedupe_key(alert_type, document_id, url_source_id, message[:120])
    existing = db.scalars(
        select(models.Alert).where(
            models.Alert.dedupe_key == key,
            models.Alert.status == models.AlertStatus.pending.value,
        )
    ).first()
    if existing:
        existing.repeat_count = (existing.repeat_count or 1) + 1
        existing.last_seen_at = now
        existing.message = message
        existing.alert_level = alert_level
        existing.risk_level = risk_level
        return existing

    alert = models.Alert(
        document_id=document_id,
        url_source_id=url_source_id,
        alert_type=alert_type,
        alert_level=alert_level,
        message=message,
        status=models.AlertStatus.pending.value,
        dedupe_key=key,
        repeat_count=1,
        first_seen_at=now,
        last_seen_at=now,
        risk_level=risk_level,
    )
    db.add(alert)
    db.flush()
    return alert


def create_operational_alert(
    db: Session,
    *,
    source: models.UrlSource | None,
    alert_type: str,
    message: str,
    level: str = models.AlertLevel.medium.value,
    document_id: int | None = None,
    risk_level: str = "medium",
    high_risk: bool = False,
) -> models.Alert | None:
    """成功/低风险流程只返回 None；高风险才创建 pending alert。"""
    if not high_risk and level != models.AlertLevel.high.value:
        return None
    return upsert_pending_alert(
        db,
        alert_type=alert_type,
        message=message,
        alert_level=level,
        risk_level=risk_level,
        dedupe_key=build_alert_dedupe_key(alert_type, source.id if source else None, document_id, message[:120]),
        document_id=document_id,
        url_source_id=source.id if source else None,
    )


def auto_handle_pending_alerts(db: Session, handled_by: str = SYSTEM_ALERT_HANDLER) -> int:
    """保留兼容入口，但默认不再在启动时批量消警。"""
    updated = (
        db.query(models.Alert)
        .filter(models.Alert.status == models.AlertStatus.pending.value)
        .update(
            {
                "status": models.AlertStatus.handled.value,
                "handled_at": datetime.now(UTC),
                "handled_by": handled_by,
            },
            synchronize_session=False,
        )
    )
    if updated:
        db.commit()
    return int(updated or 0)
