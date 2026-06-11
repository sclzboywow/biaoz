"""add operational log compaction indexes

Revision ID: 20260611_0008
Revises: 20260610_0007
Create Date: 2026-06-11
"""

from alembic import op


revision = "20260611_0008"
down_revision = "20260610_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_check_logs_throttle_lookup",
        "check_logs",
        ["url_source_id", "result", "status_code", "created_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_process_audit_logs_throttle_lookup",
        "process_audit_logs",
        ["process_name", "action", "target_type", "target_id", "status", "created_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_standard_change_logs_field_name",
        "standard_change_logs",
        ["field_name"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_source_status_sync_logs_exact_lookup",
        "source_status_sync_logs",
        ["standard_resource_id", "document_id", "old_status", "new_status", "sync_action"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_source_status_sync_logs_status_pair",
        "source_status_sync_logs",
        ["old_status", "new_status"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_alerts_status_created",
        "alerts",
        ["status", "created_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_status_created", table_name="alerts", if_exists=True)
    op.drop_index("ix_source_status_sync_logs_status_pair", table_name="source_status_sync_logs", if_exists=True)
    op.drop_index("ix_source_status_sync_logs_exact_lookup", table_name="source_status_sync_logs", if_exists=True)
    op.drop_index("ix_standard_change_logs_field_name", table_name="standard_change_logs", if_exists=True)
    op.drop_index("ix_process_audit_logs_throttle_lookup", table_name="process_audit_logs", if_exists=True)
    op.drop_index("ix_check_logs_throttle_lookup", table_name="check_logs", if_exists=True)
