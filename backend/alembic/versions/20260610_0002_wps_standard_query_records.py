"""wps standard query staging table

Revision ID: 20260610_0002
Revises: 20260528_0001
Create Date: 2026-06-10
"""

from alembic import op
import sqlalchemy as sa

revision = "20260610_0002"
down_revision = "20260528_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wps_standard_query_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wps_record_id", sa.String(length=64), nullable=False),
        sa.Column("serial_no", sa.Integer(), nullable=True),
        sa.Column("file_no", sa.Text(), nullable=True),
        sa.Column("file_name", sa.Text(), nullable=True),
        sa.Column("impl_status", sa.String(length=80), nullable=True),
        sa.Column("link_url", sa.Text(), nullable=True),
        sa.Column("goto_url", sa.Text(), nullable=True),
        sa.Column("fields_json", sa.Text(), nullable=False),
        sa.Column("wps_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_sheet", sa.String(length=120), nullable=False, server_default="标准查询系统"),
        sa.Column("governance_status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wps_record_id", name="uq_wps_standard_query_records_wps_record_id"),
    )
    op.create_index("ix_wps_standard_query_records_id", "wps_standard_query_records", ["id"], unique=False)
    op.create_index("ix_wps_standard_query_records_wps_record_id", "wps_standard_query_records", ["wps_record_id"], unique=False)
    op.create_index("ix_wps_standard_query_records_serial_no", "wps_standard_query_records", ["serial_no"], unique=False)
    op.create_index("ix_wps_standard_query_records_file_no", "wps_standard_query_records", ["file_no"], unique=False)
    op.create_index("ix_wps_standard_query_records_impl_status", "wps_standard_query_records", ["impl_status"], unique=False)
    op.create_index("ix_wps_standard_query_records_governance_status", "wps_standard_query_records", ["governance_status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_wps_standard_query_records_governance_status", table_name="wps_standard_query_records")
    op.drop_index("ix_wps_standard_query_records_impl_status", table_name="wps_standard_query_records")
    op.drop_index("ix_wps_standard_query_records_file_no", table_name="wps_standard_query_records")
    op.drop_index("ix_wps_standard_query_records_serial_no", table_name="wps_standard_query_records")
    op.drop_index("ix_wps_standard_query_records_wps_record_id", table_name="wps_standard_query_records")
    op.drop_index("ix_wps_standard_query_records_id", table_name="wps_standard_query_records")
    op.drop_table("wps_standard_query_records")
