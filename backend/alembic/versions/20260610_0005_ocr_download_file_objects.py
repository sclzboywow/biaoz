"""ocr download tasks and file objects

Revision ID: 20260610_0005
Revises: 20260610_0004
Create Date: 2026-06-10
"""

from alembic import op
import sqlalchemy as sa

revision = "20260610_0005"
down_revision = "20260610_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_hash", sa.String(length=128), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_ext", sa.String(length=20), nullable=True),
        sa.Column("mime_type", sa.String(length=120), nullable=True),
        sa.Column("storage_backend", sa.String(length=40), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("baidu_pan_uri", sa.Text(), nullable=True),
        sa.Column("minio_object_key", sa.Text(), nullable=True),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("pdf_valid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pdf_validation_status", sa.String(length=40), nullable=True),
        sa.Column("pdf_page_count", sa.Integer(), nullable=True),
        sa.Column("pdf_title", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_hash", name="uq_file_objects_file_hash"),
    )
    op.create_index("ix_file_objects_id", "file_objects", ["id"], unique=False)
    op.create_index("ix_file_objects_file_hash", "file_objects", ["file_hash"], unique=False)
    op.create_index("ix_file_objects_pdf_valid", "file_objects", ["pdf_valid"], unique=False)

    op.create_table(
        "ocr_download_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column("url_source_id", sa.Integer(), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("standard_no", sa.String(length=120), nullable=True),
        sa.Column("standard_name", sa.String(length=500), nullable=True),
        sa.Column("download_url", sa.Text(), nullable=True),
        sa.Column("captcha_url", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="PENDING"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=120), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_id", sa.Integer(), nullable=True),
        sa.Column("file_object_id", sa.Integer(), nullable=True),
        sa.Column("host", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["resource_id"], ["standard_resources.id"]),
        sa.ForeignKeyConstraint(["url_source_id"], ["url_sources.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["trusted_sources.id"]),
        sa.ForeignKeyConstraint(["decision_id"], ["governance_decisions.id"]),
        sa.ForeignKeyConstraint(["file_object_id"], ["file_objects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ocr_download_tasks_id", "ocr_download_tasks", ["id"], unique=False)
    op.create_index("ix_ocr_download_tasks_resource_id", "ocr_download_tasks", ["resource_id"], unique=False)
    op.create_index("ix_ocr_download_tasks_status", "ocr_download_tasks", ["status"], unique=False)
    op.create_index("ix_ocr_download_tasks_priority", "ocr_download_tasks", ["priority"], unique=False)
    op.create_index("ix_ocr_download_tasks_host", "ocr_download_tasks", ["host"], unique=False)
    op.create_index("ix_ocr_download_tasks_next_retry_at", "ocr_download_tasks", ["next_retry_at"], unique=False)

    op.add_column("document_versions", sa.Column("file_object_id", sa.Integer(), nullable=True))
    op.add_column("document_versions", sa.Column("original_file_name", sa.String(length=500), nullable=True))
    op.create_foreign_key(
        "fk_document_versions_file_object_id",
        "document_versions",
        "file_objects",
        ["file_object_id"],
        ["id"],
    )
    op.create_index("ix_document_versions_file_object_id", "document_versions", ["file_object_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_document_versions_file_object_id", table_name="document_versions")
    op.drop_constraint("fk_document_versions_file_object_id", "document_versions", type_="foreignkey")
    op.drop_column("document_versions", "original_file_name")
    op.drop_column("document_versions", "file_object_id")

    op.drop_index("ix_ocr_download_tasks_next_retry_at", table_name="ocr_download_tasks")
    op.drop_index("ix_ocr_download_tasks_host", table_name="ocr_download_tasks")
    op.drop_index("ix_ocr_download_tasks_priority", table_name="ocr_download_tasks")
    op.drop_index("ix_ocr_download_tasks_status", table_name="ocr_download_tasks")
    op.drop_index("ix_ocr_download_tasks_resource_id", table_name="ocr_download_tasks")
    op.drop_index("ix_ocr_download_tasks_id", table_name="ocr_download_tasks")
    op.drop_table("ocr_download_tasks")

    op.drop_index("ix_file_objects_pdf_valid", table_name="file_objects")
    op.drop_index("ix_file_objects_file_hash", table_name="file_objects")
    op.drop_index("ix_file_objects_id", table_name="file_objects")
    op.drop_table("file_objects")
