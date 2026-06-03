from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import models


SYSTEM_ALERT_HANDLER = "system-auto"


def mark_alert_auto_handled(alert: models.Alert, handled_by: str = SYSTEM_ALERT_HANDLER) -> models.Alert:
    alert.status = models.AlertStatus.handled.value
    alert.handled_at = alert.handled_at or datetime.now(UTC)
    alert.handled_by = alert.handled_by or handled_by
    return alert


def auto_handle_pending_alerts(db: Session, handled_by: str = SYSTEM_ALERT_HANDLER) -> int:
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
