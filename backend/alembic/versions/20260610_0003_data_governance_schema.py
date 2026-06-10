"""data governance schema: trusted/url source profiling and governance tables

Revision ID: 20260610_0003
Revises: 20260610_0002
Create Date: 2026-06-10
"""

from alembic import op
import sqlalchemy as sa

revision = "20260610_0003"
down_revision = "20260610_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trusted_sources", sa.Column("source_role", sa.String(length=40), nullable=True))
    op.add_column("trusted_sources", sa.Column("domain", sa.String(length=255), nullable=True))
    op.add_column("trusted_sources", sa.Column("status_authority_weight", sa.Integer(), nullable=True))
    op.add_column("trusted_sources", sa.Column("fulltext_weight", sa.Integer(), nullable=True))
    op.add_column("trusted_sources", sa.Column("metadata_weight", sa.Integer(), nullable=True))
    op.add_column("trusted_sources", sa.Column("source_health_score", sa.Integer(), nullable=True))
    op.add_column(
        "trusted_sources",
        sa.Column("governance_status", sa.String(length=40), nullable=False, server_default="pending"),
    )

    op.add_column("url_sources", sa.Column("host", sa.String(length=255), nullable=True))
    op.add_column("url_sources", sa.Column("url_type", sa.String(length=40), nullable=True))
    op.add_column("url_sources", sa.Column("file_ext", sa.String(length=20), nullable=True))
    op.add_column("url_sources", sa.Column("is_official_domain", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("url_sources", sa.Column("is_cloud_drive", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("url_sources", sa.Column("is_probable_pdf", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column(
        "url_sources",
        sa.Column("is_probable_detail_page", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("url_sources", sa.Column("source_quality_score", sa.Integer(), nullable=True))
    op.add_column(
        "url_sources",
        sa.Column("governance_status", sa.String(length=40), nullable=False, server_default="pending"),
    )
    op.add_column("url_sources", sa.Column("duplicate_group_key", sa.String(length=64), nullable=True))

    op.create_index("ix_trusted_sources_source_role", "trusted_sources", ["source_role"], unique=False)
    op.create_index("ix_trusted_sources_domain", "trusted_sources", ["domain"], unique=False)
    op.create_index("ix_trusted_sources_source_health_score", "trusted_sources", ["source_health_score"], unique=False)
    op.create_index("ix_trusted_sources_governance_status", "trusted_sources", ["governance_status"], unique=False)

    op.create_index("ix_url_sources_host", "url_sources", ["host"], unique=False)
    op.create_index("ix_url_sources_url_type", "url_sources", ["url_type"], unique=False)
    op.create_index("ix_url_sources_file_ext", "url_sources", ["file_ext"], unique=False)
    op.create_index("ix_url_sources_is_official_domain", "url_sources", ["is_official_domain"], unique=False)
    op.create_index("ix_url_sources_is_cloud_drive", "url_sources", ["is_cloud_drive"], unique=False)
    op.create_index("ix_url_sources_is_probable_pdf", "url_sources", ["is_probable_pdf"], unique=False)
    op.create_index("ix_url_sources_is_probable_detail_page", "url_sources", ["is_probable_detail_page"], unique=False)
    op.create_index("ix_url_sources_source_quality_score", "url_sources", ["source_quality_score"], unique=False)
    op.create_index("ix_url_sources_governance_status", "url_sources", ["governance_status"], unique=False)
    op.create_index("ix_url_sources_duplicate_group_key", "url_sources", ["duplicate_group_key"], unique=False)

    op.create_table(
        "source_governance_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("config_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_governance_runs_id", "source_governance_runs", ["id"], unique=False)
    op.create_index("ix_source_governance_runs_run_type", "source_governance_runs", ["run_type"], unique=False)
    op.create_index("ix_source_governance_runs_status", "source_governance_runs", ["status"], unique=False)

    op.create_table(
        "source_record_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("url_source_id", sa.Integer(), nullable=True),
        sa.Column("trusted_source_id", sa.Integer(), nullable=True),
        sa.Column("candidate_type", sa.String(length=80), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("host", sa.String(length=255), nullable=True),
        sa.Column("url_type", sa.String(length=40), nullable=True),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("duplicate_group_key", sa.String(length=64), nullable=True),
        sa.Column("governance_status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("evidence_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["source_governance_runs.id"]),
        sa.ForeignKeyConstraint(["trusted_source_id"], ["trusted_sources.id"]),
        sa.ForeignKeyConstraint(["url_source_id"], ["url_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_record_candidates_id", "source_record_candidates", ["id"], unique=False)
    op.create_index("ix_source_record_candidates_run_id", "source_record_candidates", ["run_id"], unique=False)
    op.create_index("ix_source_record_candidates_url_source_id", "source_record_candidates", ["url_source_id"], unique=False)
    op.create_index("ix_source_record_candidates_trusted_source_id", "source_record_candidates", ["trusted_source_id"], unique=False)
    op.create_index("ix_source_record_candidates_candidate_type", "source_record_candidates", ["candidate_type"], unique=False)
    op.create_index("ix_source_record_candidates_host", "source_record_candidates", ["host"], unique=False)
    op.create_index("ix_source_record_candidates_url_type", "source_record_candidates", ["url_type"], unique=False)
    op.create_index("ix_source_record_candidates_quality_score", "source_record_candidates", ["quality_score"], unique=False)
    op.create_index("ix_source_record_candidates_duplicate_group_key", "source_record_candidates", ["duplicate_group_key"], unique=False)
    op.create_index("ix_source_record_candidates_governance_status", "source_record_candidates", ["governance_status"], unique=False)

    op.create_table(
        "governance_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(length=120), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["source_governance_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_governance_decisions_id", "governance_decisions", ["id"], unique=False)
    op.create_index("ix_governance_decisions_run_id", "governance_decisions", ["run_id"], unique=False)
    op.create_index("ix_governance_decisions_target_type", "governance_decisions", ["target_type"], unique=False)
    op.create_index("ix_governance_decisions_target_id", "governance_decisions", ["target_id"], unique=False)
    op.create_index("ix_governance_decisions_decision", "governance_decisions", ["decision"], unique=False)

    op.create_table(
        "process_audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_name", sa.String(length=120), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="ok"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("detail_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_process_audit_logs_id", "process_audit_logs", ["id"], unique=False)
    op.create_index("ix_process_audit_logs_process_name", "process_audit_logs", ["process_name"], unique=False)
    op.create_index("ix_process_audit_logs_action", "process_audit_logs", ["action"], unique=False)
    op.create_index("ix_process_audit_logs_target_type", "process_audit_logs", ["target_type"], unique=False)
    op.create_index("ix_process_audit_logs_target_id", "process_audit_logs", ["target_id"], unique=False)
    op.create_index("ix_process_audit_logs_status", "process_audit_logs", ["status"], unique=False)
    op.create_index("ix_process_audit_logs_created_at", "process_audit_logs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_process_audit_logs_created_at", table_name="process_audit_logs")
    op.drop_index("ix_process_audit_logs_status", table_name="process_audit_logs")
    op.drop_index("ix_process_audit_logs_target_id", table_name="process_audit_logs")
    op.drop_index("ix_process_audit_logs_target_type", table_name="process_audit_logs")
    op.drop_index("ix_process_audit_logs_action", table_name="process_audit_logs")
    op.drop_index("ix_process_audit_logs_process_name", table_name="process_audit_logs")
    op.drop_index("ix_process_audit_logs_id", table_name="process_audit_logs")
    op.drop_table("process_audit_logs")

    op.drop_index("ix_governance_decisions_decision", table_name="governance_decisions")
    op.drop_index("ix_governance_decisions_target_id", table_name="governance_decisions")
    op.drop_index("ix_governance_decisions_target_type", table_name="governance_decisions")
    op.drop_index("ix_governance_decisions_run_id", table_name="governance_decisions")
    op.drop_index("ix_governance_decisions_id", table_name="governance_decisions")
    op.drop_table("governance_decisions")

    op.drop_index("ix_source_record_candidates_governance_status", table_name="source_record_candidates")
    op.drop_index("ix_source_record_candidates_duplicate_group_key", table_name="source_record_candidates")
    op.drop_index("ix_source_record_candidates_quality_score", table_name="source_record_candidates")
    op.drop_index("ix_source_record_candidates_url_type", table_name="source_record_candidates")
    op.drop_index("ix_source_record_candidates_host", table_name="source_record_candidates")
    op.drop_index("ix_source_record_candidates_candidate_type", table_name="source_record_candidates")
    op.drop_index("ix_source_record_candidates_trusted_source_id", table_name="source_record_candidates")
    op.drop_index("ix_source_record_candidates_url_source_id", table_name="source_record_candidates")
    op.drop_index("ix_source_record_candidates_run_id", table_name="source_record_candidates")
    op.drop_index("ix_source_record_candidates_id", table_name="source_record_candidates")
    op.drop_table("source_record_candidates")

    op.drop_index("ix_source_governance_runs_status", table_name="source_governance_runs")
    op.drop_index("ix_source_governance_runs_run_type", table_name="source_governance_runs")
    op.drop_index("ix_source_governance_runs_id", table_name="source_governance_runs")
    op.drop_table("source_governance_runs")

    op.drop_index("ix_url_sources_duplicate_group_key", table_name="url_sources")
    op.drop_index("ix_url_sources_governance_status", table_name="url_sources")
    op.drop_index("ix_url_sources_source_quality_score", table_name="url_sources")
    op.drop_index("ix_url_sources_is_probable_detail_page", table_name="url_sources")
    op.drop_index("ix_url_sources_is_probable_pdf", table_name="url_sources")
    op.drop_index("ix_url_sources_is_cloud_drive", table_name="url_sources")
    op.drop_index("ix_url_sources_is_official_domain", table_name="url_sources")
    op.drop_index("ix_url_sources_file_ext", table_name="url_sources")
    op.drop_index("ix_url_sources_url_type", table_name="url_sources")
    op.drop_index("ix_url_sources_host", table_name="url_sources")
    op.drop_column("url_sources", "duplicate_group_key")
    op.drop_column("url_sources", "governance_status")
    op.drop_column("url_sources", "source_quality_score")
    op.drop_column("url_sources", "is_probable_detail_page")
    op.drop_column("url_sources", "is_probable_pdf")
    op.drop_column("url_sources", "is_cloud_drive")
    op.drop_column("url_sources", "is_official_domain")
    op.drop_column("url_sources", "file_ext")
    op.drop_column("url_sources", "url_type")
    op.drop_column("url_sources", "host")

    op.drop_index("ix_trusted_sources_governance_status", table_name="trusted_sources")
    op.drop_index("ix_trusted_sources_source_health_score", table_name="trusted_sources")
    op.drop_index("ix_trusted_sources_domain", table_name="trusted_sources")
    op.drop_index("ix_trusted_sources_source_role", table_name="trusted_sources")
    op.drop_column("trusted_sources", "governance_status")
    op.drop_column("trusted_sources", "source_health_score")
    op.drop_column("trusted_sources", "metadata_weight")
    op.drop_column("trusted_sources", "fulltext_weight")
    op.drop_column("trusted_sources", "status_authority_weight")
    op.drop_column("trusted_sources", "domain")
    op.drop_column("trusted_sources", "source_role")
