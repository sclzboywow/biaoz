from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from sqlalchemy import delete  # noqa: E402

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive/delete low-value operational logs.")
    parser.add_argument("--success-days", type=int, default=90)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cutoff = datetime.now(UTC) - timedelta(days=args.success_days)
    with SessionLocal() as db:
        success_check_logs = db.query(models.CheckLog).filter(
            models.CheckLog.created_at < cutoff,
            models.CheckLog.result.in_(["无变化", "鏃犲彉鍖?"]),
            models.CheckLog.error_message.is_(None),
        )
        handled_alerts = db.query(models.Alert).filter(
            models.Alert.status != models.AlertStatus.pending.value,
            models.Alert.created_at < cutoff,
        )
        success_count = success_check_logs.count()
        alert_count = handled_alerts.count()
        print(f"cutoff={cutoff.isoformat()}")
        print(f"success_check_logs={success_count}")
        print(f"handled_alerts={alert_count}")
        if not args.dry_run:
            db.execute(
                delete(models.CheckLog).where(
                    models.CheckLog.created_at < cutoff,
                    models.CheckLog.result.in_(["无变化", "鏃犲彉鍖?"]),
                    models.CheckLog.error_message.is_(None),
                )
            )
            db.execute(
                delete(models.Alert).where(
                    models.Alert.status != models.AlertStatus.pending.value,
                    models.Alert.created_at < cutoff,
                )
            )
            db.commit()


if __name__ == "__main__":
    main()
