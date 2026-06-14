"""Add document classification fields."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260614_0011"
down_revision = "20260612_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("classification_decision", sa.String(length=40), nullable=True))
    op.add_column("documents", sa.Column("classification_confidence_score", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("classification_risk_level", sa.String(length=20), nullable=True))
    op.add_column("documents", sa.Column("classification_reason", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("matched_resource_id", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("standard_level", sa.String(length=40), nullable=True))
    op.create_foreign_key(
        "fk_documents_matched_resource_id",
        "documents",
        "standard_resources",
        ["matched_resource_id"],
        ["id"],
    )
    op.create_index("ix_documents_classification_decision", "documents", ["classification_decision"])
    op.create_index("ix_documents_classification_confidence_score", "documents", ["classification_confidence_score"])
    op.create_index("ix_documents_classification_risk_level", "documents", ["classification_risk_level"])
    op.create_index("ix_documents_matched_resource_id", "documents", ["matched_resource_id"])
    op.create_index("ix_documents_standard_level", "documents", ["standard_level"])


def downgrade() -> None:
    op.drop_index("ix_documents_standard_level", table_name="documents")
    op.drop_index("ix_documents_matched_resource_id", table_name="documents")
    op.drop_index("ix_documents_classification_risk_level", table_name="documents")
    op.drop_index("ix_documents_classification_confidence_score", table_name="documents")
    op.drop_index("ix_documents_classification_decision", table_name="documents")
    op.drop_constraint("fk_documents_matched_resource_id", "documents", type_="foreignkey")
    op.drop_column("documents", "standard_level")
    op.drop_column("documents", "matched_resource_id")
    op.drop_column("documents", "classification_reason")
    op.drop_column("documents", "classification_risk_level")
    op.drop_column("documents", "classification_confidence_score")
    op.drop_column("documents", "classification_decision")
