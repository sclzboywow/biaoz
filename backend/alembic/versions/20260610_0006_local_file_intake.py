"""local file intake recognition tables

Revision ID: 20260610_0006
Revises: 20260610_0005
Create Date: 2026-06-10
"""

from alembic import op
import sqlalchemy as sa

revision = "20260610_0006"
down_revision = "20260610_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_file_intake_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("original_file_name", sa.String(length=500), nullable=False),
        sa.Column("temp_file_path", sa.Text(), nullable=False),
        sa.Column("file_hash", sa.String(length=128), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_type", sa.String(length=40), nullable=True),
        sa.Column("mime_type", sa.String(length=120), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("extracted_text_sample", sa.Text(), nullable=True),
        sa.Column("extracted_standard_no", sa.String(length=160), nullable=True),
        sa.Column("normalized_standard_no", sa.String(length=160), nullable=True),
        sa.Column("extracted_title", sa.String(length=500), nullable=True),
        sa.Column("extracted_publish_date", sa.Date(), nullable=True),
        sa.Column("extracted_effective_date", sa.Date(), nullable=True),
        sa.Column("recognition_status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("decision", sa.String(length=40), nullable=True),
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        sa.Column("risk_level", sa.String(length=20), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=120), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_action", sa.String(length=40), nullable=True),
        sa.Column("linked_document_id", sa.Integer(), nullable=True),
        sa.Column("linked_version_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["linked_document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["linked_version_id"], ["document_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_local_file_intake_tasks_id", "local_file_intake_tasks", ["id"], unique=False)
    op.create_index("ix_local_file_intake_tasks_file_hash", "local_file_intake_tasks", ["file_hash"], unique=False)
    op.create_index("ix_local_file_intake_tasks_extracted_standard_no", "local_file_intake_tasks", ["extracted_standard_no"], unique=False)
    op.create_index("ix_local_file_intake_tasks_normalized_standard_no", "local_file_intake_tasks", ["normalized_standard_no"], unique=False)
    op.create_index("ix_local_file_intake_tasks_recognition_status", "local_file_intake_tasks", ["recognition_status"], unique=False)
    op.create_index("ix_local_file_intake_tasks_decision", "local_file_intake_tasks", ["decision"], unique=False)
    op.create_index("ix_local_file_intake_tasks_linked_document_id", "local_file_intake_tasks", ["linked_document_id"], unique=False)
    op.create_index("ix_local_file_intake_tasks_linked_version_id", "local_file_intake_tasks", ["linked_version_id"], unique=False)

    op.create_table(
        "local_file_recognition_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("candidate_type", sa.String(length=40), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("source_name", sa.String(length=255), nullable=True),
        sa.Column("standard_no", sa.String(length=160), nullable=True),
        sa.Column("normalized_standard_no", sa.String(length=160), nullable=True),
        sa.Column("standard_name", sa.String(length=500), nullable=True),
        sa.Column("source_status", sa.String(length=80), nullable=True),
        sa.Column("publish_date", sa.Date(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("abolish_date", sa.Date(), nullable=True),
        sa.Column("detail_url", sa.Text(), nullable=True),
        sa.Column("pdf_trial_url", sa.Text(), nullable=True),
        sa.Column("match_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("match_reason", sa.Text(), nullable=True),
        sa.Column("decision_advice", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["local_file_intake_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_local_file_recognition_candidates_id", "local_file_recognition_candidates", ["id"], unique=False)
    op.create_index("ix_local_file_recognition_candidates_task_id", "local_file_recognition_candidates", ["task_id"], unique=False)
    op.create_index("ix_local_file_recognition_candidates_candidate_type", "local_file_recognition_candidates", ["candidate_type"], unique=False)
    op.create_index("ix_local_file_recognition_candidates_candidate_id", "local_file_recognition_candidates", ["candidate_id"], unique=False)
    op.create_index("ix_local_file_recognition_candidates_source_id", "local_file_recognition_candidates", ["source_id"], unique=False)

    op.create_table(
        "local_file_intake_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(length=80), nullable=False),
        sa.Column("result", sa.String(length=40), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("detail_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["local_file_intake_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_local_file_intake_logs_id", "local_file_intake_logs", ["id"], unique=False)
    op.create_index("ix_local_file_intake_logs_task_id", "local_file_intake_logs", ["task_id"], unique=False)
    op.create_index("ix_local_file_intake_logs_created_at", "local_file_intake_logs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_local_file_intake_logs_created_at", table_name="local_file_intake_logs")
    op.drop_index("ix_local_file_intake_logs_task_id", table_name="local_file_intake_logs")
    op.drop_index("ix_local_file_intake_logs_id", table_name="local_file_intake_logs")
    op.drop_table("local_file_intake_logs")

    op.drop_index("ix_local_file_recognition_candidates_source_id", table_name="local_file_recognition_candidates")
    op.drop_index("ix_local_file_recognition_candidates_candidate_id", table_name="local_file_recognition_candidates")
    op.drop_index("ix_local_file_recognition_candidates_candidate_type", table_name="local_file_recognition_candidates")
    op.drop_index("ix_local_file_recognition_candidates_task_id", table_name="local_file_recognition_candidates")
    op.drop_index("ix_local_file_recognition_candidates_id", table_name="local_file_recognition_candidates")
    op.drop_table("local_file_recognition_candidates")

    op.drop_index("ix_local_file_intake_tasks_linked_version_id", table_name="local_file_intake_tasks")
    op.drop_index("ix_local_file_intake_tasks_linked_document_id", table_name="local_file_intake_tasks")
    op.drop_index("ix_local_file_intake_tasks_decision", table_name="local_file_intake_tasks")
    op.drop_index("ix_local_file_intake_tasks_recognition_status", table_name="local_file_intake_tasks")
    op.drop_index("ix_local_file_intake_tasks_normalized_standard_no", table_name="local_file_intake_tasks")
    op.drop_index("ix_local_file_intake_tasks_extracted_standard_no", table_name="local_file_intake_tasks")
    op.drop_index("ix_local_file_intake_tasks_file_hash", table_name="local_file_intake_tasks")
    op.drop_index("ix_local_file_intake_tasks_id", table_name="local_file_intake_tasks")
    op.drop_table("local_file_intake_tasks")
