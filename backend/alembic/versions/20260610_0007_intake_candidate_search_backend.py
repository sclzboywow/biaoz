"""add search_backend to local file intake candidates

Revision ID: 20260610_0007
Revises: 20260610_0006
Create Date: 2026-06-10
"""

from alembic import op
import sqlalchemy as sa

revision = "20260610_0007"
down_revision = "20260610_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "local_file_recognition_candidates",
        sa.Column("search_backend", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("local_file_recognition_candidates", "search_backend")
