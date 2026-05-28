from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from sqlalchemy import delete  # noqa: E402

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402


SUCCESS_RESULTS = {
    "无变化",
    "新增",
    "更新",
    "鏃犲彉鍖?",
    "鏂板",
    "鏇存柊",
}


def month_key(value: datetime | None) -> str:
    if value is None:
        return "unknown"
    return value.strftime("%Y-%m")


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive low-value operational logs and keep evidence/status history.")
    parser.add_argument("--success-days", type=int, default=90)
    parser.add_argument("--handled-alert-days", type=int, default=180)
    parser.add_argument("--archive-dir", type=Path, default=ROOT / "logs" / "archives")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    args.archive_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    success_cutoff = now - timedelta(days=args.success_days)
    handled_alert_cutoff = now - timedelta(days=args.handled_alert_days)

    with SessionLocal() as db:
        success_rows = list(
            db.query(models.CheckLog.result, models.CheckLog.created_at)
            .filter(
                models.CheckLog.created_at < success_cutoff,
                models.CheckLog.result.in_(SUCCESS_RESULTS),
                models.CheckLog.error_message.is_(None),
            )
        )
        success_logs = Counter((month_key(created_at), result) for result, created_at in success_rows)
        summary = {
            "generated_at": now.isoformat(),
            "success_cutoff": success_cutoff.isoformat(),
            "handled_alert_cutoff": handled_alert_cutoff.isoformat(),
            "check_logs": [
                {"month": month, "result": result, "count": count}
                for (month, result), count in sorted(success_logs.items())
            ],
        }

        handled_rows = list(
            db.query(models.Alert.alert_type, models.Alert.created_at)
            .filter(
                models.Alert.status != models.AlertStatus.pending.value,
                models.Alert.created_at < handled_alert_cutoff,
            )
        )
        handled_alerts = Counter((month_key(created_at), alert_type) for alert_type, created_at in handled_rows)
        summary["handled_alerts"] = [
            {"month": month, "alert_type": alert_type, "count": count}
            for (month, alert_type), count in sorted(handled_alerts.items())
        ]

        totals = Counter()
        totals["success_check_logs"] = sum(item["count"] for item in summary["check_logs"])
        totals["handled_alerts"] = sum(item["count"] for item in summary["handled_alerts"])
        summary["totals"] = dict(totals)

        archive_path = args.archive_dir / f"operational-log-summary-{now.strftime('%Y%m%d-%H%M%S')}.json"
        archive_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"archive_path={archive_path}")
        print(f"success_check_logs={totals['success_check_logs']}")
        print(f"handled_alerts={totals['handled_alerts']}")
        print("kept_long_term=failed check logs, source sync logs, change logs, evidence logs")

        if not args.dry_run:
            db.execute(
                delete(models.CheckLog).where(
                    models.CheckLog.created_at < success_cutoff,
                    models.CheckLog.result.in_(SUCCESS_RESULTS),
                    models.CheckLog.error_message.is_(None),
                )
            )
            db.execute(
                delete(models.Alert).where(
                    models.Alert.status != models.AlertStatus.pending.value,
                    models.Alert.created_at < handled_alert_cutoff,
                )
            )
            db.commit()


if __name__ == "__main__":
    main()
