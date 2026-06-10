"""governance decision phase3: resource decisions, alert dedupe, audit fields

Revision ID: 20260610_0004
Revises: 20260610_0003
Create Date: 2026-06-10
"""

from alembic import op
import sqlalchemy as sa

revision = "20260610_0004"
down_revision = "20260610_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("standard_resources", sa.Column("auto_decision", sa.String(length=40), nullable=True))
    op.add_column("standard_resources", sa.Column("confidence_score", sa.Integer(), nullable=True))
    op.add_column("standard_resources", sa.Column("decision_reason", sa.Text(), nullable=True))
    op.add_column("standard_resources", sa.Column("risk_level", sa.String(length=20), nullable=True))
    op.add_column("standard_resources", sa.Column("last_governed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_standard_resources_auto_decision", "standard_resources", ["auto_decision"], unique=False)
    op.create_index("ix_standard_resources_confidence_score", "standard_resources", ["confidence_score"], unique=False)
    op.create_index("ix_standard_resources_risk_level", "standard_resources", ["risk_level"], unique=False)
    op.create_index("ix_standard_resources_last_governed_at", "standard_resources", ["last_governed_at"], unique=False)

    op.add_column("governance_decisions", sa.Column("confidence_score", sa.Integer(), nullable=True))
    op.add_column("governance_decisions", sa.Column("decision_reason", sa.Text(), nullable=True))
    op.add_column("governance_decisions", sa.Column("evidence_count", sa.Integer(), nullable=True))
    op.add_column("governance_decisions", sa.Column("highest_source_level", sa.String(length=30), nullable=True))
    op.add_column("governance_decisions", sa.Column("highest_source_weight", sa.Integer(), nullable=True))
    op.add_column("governance_decisions", sa.Column("conflict_count", sa.Integer(), nullable=True))
    op.add_column("governance_decisions", sa.Column("risk_level", sa.String(length=20), nullable=True))
    op.create_index("ix_governance_decisions_confidence_score", "governance_decisions", ["confidence_score"], unique=False)
    op.create_index("ix_governance_decisions_risk_level", "governance_decisions", ["risk_level"], unique=False)

    op.add_column("alerts", sa.Column("dedupe_key", sa.String(length=128), nullable=True))
    op.add_column("alerts", sa.Column("repeat_count", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("alerts", sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("alerts", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("alerts", sa.Column("risk_level", sa.String(length=20), nullable=True))
    op.create_index("ix_alerts_dedupe_key", "alerts", ["dedupe_key"], unique=False)
    op.create_index("ix_alerts_risk_level", "alerts", ["risk_level"], unique=False)

    op.add_column("process_audit_logs", sa.Column("process_type", sa.String(length=80), nullable=True))
    op.add_column("process_audit_logs", sa.Column("step_name", sa.String(length=80), nullable=True))
    op.add_column("process_audit_logs", sa.Column("source_id", sa.Integer(), nullable=True))
    op.add_column("process_audit_logs", sa.Column("confidence_score", sa.Integer(), nullable=True))
    op.add_column("process_audit_logs", sa.Column("input_summary", sa.Text(), nullable=True))
    op.add_column("process_audit_logs", sa.Column("output_summary", sa.Text(), nullable=True))
    op.add_column("process_audit_logs", sa.Column("error_message", sa.Text(), nullable=True))
    op.create_index("ix_process_audit_logs_process_type", "process_audit_logs", ["process_type"], unique=False)
    op.create_index("ix_process_audit_logs_step_name", "process_audit_logs", ["step_name"], unique=False)
    op.create_index("ix_process_audit_logs_source_id", "process_audit_logs", ["source_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_process_audit_logs_source_id", table_name="process_audit_logs")
    op.drop_index("ix_process_audit_logs_step_name", table_name="process_audit_logs")
    op.drop_index("ix_process_audit_logs_process_type", table_name="process_audit_logs")
    op.drop_column("process_audit_logs", "error_message")
    op.drop_column("process_audit_logs", "output_summary")
    op.drop_column("process_audit_logs", "input_summary")
    op.drop_column("process_audit_logs", "confidence_score")
    op.drop_column("process_audit_logs", "source_id")
    op.drop_column("process_audit_logs", "step_name")
    op.drop_column("process_audit_logs", "process_type")

    op.drop_index("ix_alerts_risk_level", table_name="alerts")
    op.drop_index("ix_alerts_dedupe_key", table_name="alerts")
    op.drop_column("alerts", "risk_level")
    op.drop_column("alerts", "last_seen_at")
    op.drop_column("alerts", "first_seen_at")
    op.drop_column("alerts", "repeat_count")
    op.drop_column("alerts", "dedupe_key")

    op.drop_index("ix_governance_decisions_risk_level", table_name="governance_decisions")
    op.drop_index("ix_governance_decisions_confidence_score", table_name="governance_decisions")
    op.drop_column("governance_decisions", "risk_level")
    op.drop_column("governance_decisions", "conflict_count")
    op.drop_column("governance_decisions", "highest_source_weight")
    op.drop_column("governance_decisions", "highest_source_level")
    op.drop_column("governance_decisions", "evidence_count")
    op.drop_column("governance_decisions", "decision_reason")
    op.drop_column("governance_decisions", "confidence_score")

    op.drop_index("ix_standard_resources_last_governed_at", table_name="standard_resources")
    op.drop_index("ix_standard_resources_risk_level", table_name="standard_resources")
    op.drop_index("ix_standard_resources_confidence_score", table_name="standard_resources")
    op.drop_index("ix_standard_resources_auto_decision", table_name="standard_resources")
    op.drop_column("standard_resources", "last_governed_at")
    op.drop_column("standard_resources", "risk_level")
    op.drop_column("standard_resources", "decision_reason")
    op.drop_column("standard_resources", "confidence_score")
    op.drop_column("standard_resources", "auto_decision")
