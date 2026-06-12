"""add certification_records for batch-2 cx.cnca.cn source

Revision ID: 20260612_0009
Revises: 20260611_0008
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260612_0009"
down_revision = "20260611_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "certification_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("trusted_sources.id"), nullable=False),
        sa.Column("source_item_id", sa.String(length=160), nullable=False),
        sa.Column("record_type", sa.String(length=120), nullable=True),
        sa.Column("org_name", sa.String(length=500), nullable=True),
        sa.Column("certificate_no", sa.String(length=160), nullable=True),
        sa.Column("standard_refs", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("expire_date", sa.Date(), nullable=True),
        sa.Column("detail_url", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_certification_records_source_id", "certification_records", ["source_id"])
    op.create_index("ix_certification_records_source_item_id", "certification_records", ["source_item_id"])
    op.create_index("ix_certification_records_record_type", "certification_records", ["record_type"])
    op.create_index("ix_certification_records_org_name", "certification_records", ["org_name"])
    op.create_index("ix_certification_records_certificate_no", "certification_records", ["certificate_no"])
    op.create_index("ix_certification_records_status", "certification_records", ["status"])
    op.create_unique_constraint(
        "uq_certification_records_source_item",
        "certification_records",
        ["source_id", "source_item_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_certification_records_source_item", "certification_records", type_="unique")
    op.drop_index("ix_certification_records_status", table_name="certification_records")
    op.drop_index("ix_certification_records_certificate_no", table_name="certification_records")
    op.drop_index("ix_certification_records_org_name", table_name="certification_records")
    op.drop_index("ix_certification_records_record_type", table_name="certification_records")
    op.drop_index("ix_certification_records_source_item_id", table_name="certification_records")
    op.drop_index("ix_certification_records_source_id", table_name="certification_records")
    op.drop_table("certification_records")
