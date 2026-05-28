"""initial PostgreSQL schema

Revision ID: 20260528_0001
Revises:
Create Date: 2026-05-28
"""

from alembic import op

from app.database import Base
from app import models  # noqa: F401

revision = "20260528_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    op.create_index("ix_document_versions_url_source_hash", "document_versions", ["url_source_id", "file_hash"], if_not_exists=True)
    op.create_index("ix_document_versions_source_current_time", "document_versions", ["url_source_id", "is_current", "downloaded_at", "id"], if_not_exists=True)
    op.create_index("ix_document_versions_document_time", "document_versions", ["document_id", "downloaded_at", "id"], if_not_exists=True)
    op.create_index("ix_url_sources_status_id", "url_sources", ["status", "id"], if_not_exists=True)
    op.create_index("ix_alerts_status_id", "alerts", ["status", "id"], if_not_exists=True)
    op.create_index("ix_alerts_document_id", "alerts", ["document_id", "id"], if_not_exists=True)
    op.create_index("ix_alerts_url_source_id", "alerts", ["url_source_id", "id"], if_not_exists=True)
    op.create_index("ix_check_logs_url_source_id", "check_logs", ["url_source_id", "id"], if_not_exists=True)
    op.create_index("ix_check_logs_created_result", "check_logs", ["created_at", "result"], if_not_exists=True)
    op.create_index("ix_standard_resources_synced_id", "standard_resources", ["last_synced_at", "id"], if_not_exists=True)
    op.create_index("ix_standard_resources_source_status", "standard_resources", ["source_id", "source_status", "id"], if_not_exists=True)
    op.create_index("ix_source_categories_source_path", "source_categories", ["source_id", "category_path", "source_category_id"], if_not_exists=True)
    op.create_index("ix_standard_file_matches_resource_id", "standard_file_matches", ["standard_resource_id", "id"], if_not_exists=True)
    op.create_index("ix_standard_file_matches_document_id", "standard_file_matches", ["document_id", "id"], if_not_exists=True)
    op.create_index("ix_standard_change_logs_resource_time", "standard_change_logs", ["standard_resource_id", "detected_at"], if_not_exists=True)
    op.create_index("ix_standard_change_logs_document_time", "standard_change_logs", ["document_id", "detected_at"], if_not_exists=True)
    op.create_index("ix_source_status_sync_logs_resource_time", "source_status_sync_logs", ["standard_resource_id", "synced_at"], if_not_exists=True)
    op.create_index("ix_source_status_sync_logs_document_time", "source_status_sync_logs", ["document_id", "synced_at"], if_not_exists=True)
    op.create_index("ix_standard_evidence_resource_time", "standard_evidence", ["standard_resource_id", "captured_at"], if_not_exists=True)
    op.create_index("ix_standard_evidence_document_time", "standard_evidence", ["document_id", "captured_at"], if_not_exists=True)
    op.create_index("ix_standard_relations_current_resource", "standard_relations", ["current_standard_resource_id", "discovered_at"], if_not_exists=True)
    op.create_index("ix_standard_relations_related_resource", "standard_relations", ["related_standard_resource_id", "discovered_at"], if_not_exists=True)
    op.create_index("ix_collection_tasks_status_id", "collection_tasks", ["status", "id"], if_not_exists=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
