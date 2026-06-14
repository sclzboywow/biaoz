"""Add batch-2 official file URL and ingest status to standard_resources."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260612_0010"
down_revision = "20260612_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("standard_resources", sa.Column("official_file_url", sa.Text(), nullable=True))
    op.add_column("standard_resources", sa.Column("file_ingest_status", sa.String(length=40), nullable=True))
    op.create_index("ix_standard_resources_file_ingest_status", "standard_resources", ["file_ingest_status"])


def downgrade() -> None:
    op.drop_index("ix_standard_resources_file_ingest_status", table_name="standard_resources")
    op.drop_column("standard_resources", "file_ingest_status")
    op.drop_column("standard_resources", "official_file_url")
