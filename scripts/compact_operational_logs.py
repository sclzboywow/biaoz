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

from sqlalchemy import bindparam, text  # noqa: E402

from app.database import SessionLocal  # noqa: E402


MONITORED_CHANGE_FIELDS = {
    "standard_no",
    "standard_name",
    "source_status",
    "publish_date",
    "effective_date",
    "abolish_date",
    "summary",
    "change_info",
    "pdf_trial_url",
}


def statement(sql: str):
    return text(sql)


def field_filter_statement(sql: str):
    return text(sql).bindparams(bindparam("fields", expanding=True))


def scalar_int(db, sql, params: dict | None = None) -> int:
    return int(db.execute(sql if not isinstance(sql, str) else statement(sql), params or {}).scalar() or 0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compact low-value operational log rows while keeping evidence and state-change history."
    )
    parser.add_argument("--apply", action="store_true", help="Actually delete rows. Default is dry-run.")
    parser.add_argument("--check-success-days", type=int, default=30)
    parser.add_argument("--audit-ok-days", type=int, default=30)
    parser.add_argument("--handled-alert-days", type=int, default=90)
    args = parser.parse_args()

    now = datetime.now(UTC)
    check_success_cutoff = now - timedelta(days=args.check_success_days)
    audit_ok_cutoff = now - timedelta(days=args.audit_ok_days)
    handled_alert_cutoff = now - timedelta(days=args.handled_alert_days)
    monitored_fields = tuple(sorted(MONITORED_CHANGE_FIELDS))

    with SessionLocal() as db:
        counts = {
            "change_logs_runtime_fields": scalar_int(
                db,
                field_filter_statement("SELECT count(*) FROM standard_change_logs WHERE field_name NOT IN :fields"),
                {"fields": monitored_fields},
            ),
            "status_sync_noop": scalar_int(
                db,
                "SELECT count(*) FROM source_status_sync_logs WHERE old_status IS NOT DISTINCT FROM new_status",
            ),
            "status_sync_exact_duplicates": scalar_int(
                db,
                """
                SELECT count(*) FROM (
                    SELECT id,
                           row_number() OVER (
                               PARTITION BY standard_resource_id, document_id, old_status, new_status, sync_action, sync_reason
                               ORDER BY id
                           ) AS rn
                    FROM source_status_sync_logs
                ) ranked
                WHERE rn > 1
                """,
            ),
            "check_logs_old_success": scalar_int(
                db,
                """
                SELECT count(*)
                FROM check_logs
                WHERE created_at < :cutoff
                  AND change_detected = false
                  AND error_message IS NULL
                """,
                {"cutoff": check_success_cutoff},
            ),
            "process_audit_old_ok": scalar_int(
                db,
                """
                SELECT count(*)
                FROM process_audit_logs
                WHERE created_at < :cutoff
                  AND status = 'ok'
                  AND action IN (
                      'profile_url_source',
                      'make_governance_decision',
                      'alert_suppressed',
                      'create_ocr_task_from_decision'
                  )
                """,
                {"cutoff": audit_ok_cutoff},
            ),
            "handled_alerts_old": scalar_int(
                db,
                """
                SELECT count(*)
                FROM alerts
                WHERE created_at < :cutoff
                  AND status <> '未处理'
                """,
                {"cutoff": handled_alert_cutoff},
            ),
        }

        for name, count in counts.items():
            print(f"{name}={count}")

        if not args.apply:
            print("dry_run=true")
            return

        db.execute(
            field_filter_statement("DELETE FROM standard_change_logs WHERE field_name NOT IN :fields"),
            {"fields": monitored_fields},
        )
        db.execute(
            text("DELETE FROM source_status_sync_logs WHERE old_status IS NOT DISTINCT FROM new_status")
        )
        db.execute(
            text(
                """
                DELETE FROM source_status_sync_logs
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                               row_number() OVER (
                                   PARTITION BY standard_resource_id, document_id, old_status, new_status, sync_action, sync_reason
                                   ORDER BY id
                               ) AS rn
                        FROM source_status_sync_logs
                    ) ranked
                    WHERE rn > 1
                )
                """
            )
        )
        db.execute(
            text(
                """
                DELETE FROM check_logs
                WHERE created_at < :cutoff
                  AND change_detected = false
                  AND error_message IS NULL
                """
            ),
            {"cutoff": check_success_cutoff},
        )
        db.execute(
            text(
                """
                DELETE FROM process_audit_logs
                WHERE created_at < :cutoff
                  AND status = 'ok'
                  AND action IN (
                      'profile_url_source',
                      'make_governance_decision',
                      'alert_suppressed',
                      'create_ocr_task_from_decision'
                  )
                """
            ),
            {"cutoff": audit_ok_cutoff},
        )
        db.execute(
            text(
                """
                DELETE FROM alerts
                WHERE created_at < :cutoff
                  AND status <> '未处理'
                """
            ),
            {"cutoff": handled_alert_cutoff},
        )
        db.commit()
        print("dry_run=false")


if __name__ == "__main__":
    main()
