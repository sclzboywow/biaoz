from sqlalchemy import inspect, text

from app.database import engine


SQLITE_COLUMNS: dict[str, dict[str, str]] = {
    "url_sources": {
        "source_unit": "VARCHAR(255)",
        "category_id": "INTEGER",
        "error_message": "TEXT",
    },
    "documents": {
        "category_id": "INTEGER",
        "metadata_status": "VARCHAR(30) DEFAULT '系统识别'",
        "current_version_id": "INTEGER",
        "review_remark": "TEXT",
        "raw_standard_no": "VARCHAR(160)",
        "normalized_standard_no": "VARCHAR(160)",
        "standard_prefix": "VARCHAR(40)",
        "standard_main_no": "VARCHAR(80)",
        "standard_year": "VARCHAR(10)",
        "standard_revision_note": "VARCHAR(255)",
        "source_status": "VARCHAR(80)",
        "system_status": "VARCHAR(80)",
        "manual_status": "VARCHAR(80)",
    },
    "document_versions": {
        "created_at": "DATETIME",
    },
    "check_logs": {
        "check_time": "DATETIME",
        "change_detected": "BOOLEAN DEFAULT 0",
        "error_message": "TEXT",
        "created_at": "DATETIME",
    },
    "alerts": {
        "handled_by": "VARCHAR(120)",
    },
    "standard_resources": {
        "matched_document_count": "INTEGER DEFAULT 0",
        "raw_standard_no": "VARCHAR(160)",
        "normalized_standard_no": "VARCHAR(160)",
        "standard_prefix": "VARCHAR(40)",
        "standard_main_no": "VARCHAR(80)",
        "standard_year": "VARCHAR(10)",
        "standard_revision_note": "VARCHAR(255)",
        "source_status_raw": "VARCHAR(160)",
    },
    "standard_change_logs": {
        "document_id": "INTEGER",
        "document_version_id": "INTEGER",
        "evidence_summary": "TEXT",
    },
    "trusted_sources": {
        "adapter_key": "VARCHAR(120)",
        "capabilities": "TEXT",
    },
    "source_categories": {
        "sync_status": "VARCHAR(80) DEFAULT '待同步'",
        "last_sync_started_at": "DATETIME",
        "last_sync_finished_at": "DATETIME",
        "last_sync_error": "TEXT",
        "last_synced_page": "INTEGER",
        "last_seen_book_ids_hash": "VARCHAR(128)",
    },
    "collection_tasks": {
        "include_manual": "BOOLEAN DEFAULT 0",
        "batch_size": "INTEGER DEFAULT 50",
        "last_source_id": "INTEGER",
        "worker_id": "VARCHAR(120)",
        "heartbeat_at": "DATETIME",
    },
}

SQLITE_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS system_settings (
        key VARCHAR(120) PRIMARY KEY,
        value TEXT,
        value_type VARCHAR(30) DEFAULT 'string',
        label VARCHAR(120),
        description TEXT,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trusted_sources (
        id INTEGER PRIMARY KEY,
        source_name VARCHAR(120) NOT NULL UNIQUE,
        base_url TEXT NOT NULL,
        trust_level VARCHAR(30) DEFAULT 'A',
        trust_score INTEGER DEFAULT 100,
        source_type VARCHAR(120) DEFAULT '标准规范可信目录源',
        is_status_authority BOOLEAN DEFAULT 1,
        crawl_mode VARCHAR(120),
        crawl_frequency VARCHAR(80) DEFAULT 'weekly',
        enabled BOOLEAN DEFAULT 1,
        remark TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_categories (
        id INTEGER PRIMARY KEY,
        source_id INTEGER NOT NULL,
        source_category_id VARCHAR(120),
        parent_id INTEGER,
        category_name VARCHAR(120) NOT NULL,
        category_path TEXT,
        resource_count INTEGER,
        source_url TEXT,
        last_synced_at DATETIME
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS standard_resources (
        id INTEGER PRIMARY KEY,
        source_id INTEGER NOT NULL,
        source_book_id VARCHAR(120),
        source_name VARCHAR(120),
        standard_no VARCHAR(120),
        standard_name VARCHAR(500) NOT NULL,
        resource_type VARCHAR(120),
        source_status VARCHAR(80),
        system_status VARCHAR(80),
        manual_status VARCHAR(80),
        publish_date DATE,
        effective_date DATE,
        abolish_date DATE,
        storage_date DATE,
        chief_editor_unit VARCHAR(500),
        summary TEXT,
        keywords TEXT,
        source_category_path TEXT,
        detail_url TEXT,
        pdf_trial_url TEXT,
        detail_hash VARCHAR(128),
        source_confidence INTEGER DEFAULT 100,
        last_synced_at DATETIME,
        sync_status VARCHAR(80),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS standard_details (
        id INTEGER PRIMARY KEY,
        standard_resource_id INTEGER NOT NULL,
        catalog_text TEXT,
        mandatory_provisions TEXT,
        expert_interpretation TEXT,
        product_info TEXT,
        change_info TEXT,
        related_books TEXT,
        raw_html_path TEXT,
        raw_text_path TEXT,
        captured_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS standard_file_matches (
        id INTEGER PRIMARY KEY,
        standard_resource_id INTEGER NOT NULL,
        document_id INTEGER NOT NULL,
        document_version_id INTEGER,
        match_type VARCHAR(80),
        match_score INTEGER,
        match_reason TEXT,
        matched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        status VARCHAR(80) DEFAULT '待确认'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS standard_change_logs (
        id INTEGER PRIMARY KEY,
        standard_resource_id INTEGER NOT NULL,
        field_name VARCHAR(120) NOT NULL,
        old_value TEXT,
        new_value TEXT,
        change_type VARCHAR(80),
        detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        source_url TEXT,
        handled_status VARCHAR(80) DEFAULT '未处理'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_status_sync_logs (
        id INTEGER PRIMARY KEY,
        standard_resource_id INTEGER NOT NULL,
        document_id INTEGER,
        old_status VARCHAR(80),
        new_status VARCHAR(80),
        sync_action VARCHAR(120),
        sync_reason TEXT,
        synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS standard_evidence (
        id INTEGER PRIMARY KEY,
        standard_resource_id INTEGER,
        document_id INTEGER,
        source_name VARCHAR(120),
        source_level VARCHAR(30),
        source_url TEXT,
        captured_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        raw_status_text VARCHAR(160),
        parsed_status VARCHAR(80),
        page_summary TEXT,
        page_html_hash VARCHAR(128),
        evidence_note TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS standard_relations (
        id INTEGER PRIMARY KEY,
        current_standard_resource_id INTEGER,
        related_standard_resource_id INTEGER,
        current_standard_no VARCHAR(160),
        related_standard_no VARCHAR(160),
        relation_type VARCHAR(80) DEFAULT '相关',
        relation_text TEXT,
        source_url TEXT,
        discovered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        is_manual_confirmed BOOLEAN DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS collection_tasks (
        id INTEGER PRIMARY KEY,
        task_type VARCHAR(80) DEFAULT 'url_check',
        status VARCHAR(40) DEFAULT 'pending',
        total INTEGER DEFAULT 0,
        processed INTEGER DEFAULT 0,
        success INTEGER DEFAULT 0,
        failed INTEGER DEFAULT 0,
        message TEXT,
        started_at DATETIME,
        finished_at DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
]

SQLITE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_document_versions_url_source_id ON document_versions (url_source_id)",
    "CREATE INDEX IF NOT EXISTS ix_document_versions_url_source_hash ON document_versions (url_source_id, file_hash)",
    "CREATE INDEX IF NOT EXISTS ix_document_versions_document_id ON document_versions (document_id)",
    "CREATE INDEX IF NOT EXISTS ix_document_versions_source_current_time ON document_versions (url_source_id, is_current, downloaded_at, id)",
    "CREATE INDEX IF NOT EXISTS ix_document_versions_document_time ON document_versions (document_id, downloaded_at, id)",
    "CREATE INDEX IF NOT EXISTS ix_url_sources_status_id ON url_sources (status, id)",
    "CREATE INDEX IF NOT EXISTS ix_alerts_status_id ON alerts (status, id)",
    "CREATE INDEX IF NOT EXISTS ix_alerts_document_id ON alerts (document_id, id)",
    "CREATE INDEX IF NOT EXISTS ix_alerts_url_source_id ON alerts (url_source_id, id)",
    "CREATE INDEX IF NOT EXISTS ix_check_logs_url_source_id ON check_logs (url_source_id, id)",
    "CREATE INDEX IF NOT EXISTS ix_standard_resources_synced_id ON standard_resources (last_synced_at, id)",
    "CREATE INDEX IF NOT EXISTS ix_standard_resources_source_status ON standard_resources (source_id, source_status, id)",
    "CREATE INDEX IF NOT EXISTS ix_source_categories_source_path ON source_categories (source_id, category_path, source_category_id)",
    "CREATE INDEX IF NOT EXISTS ix_standard_file_matches_resource_id ON standard_file_matches (standard_resource_id, id)",
    "CREATE INDEX IF NOT EXISTS ix_standard_file_matches_document_id ON standard_file_matches (document_id, id)",
    "CREATE INDEX IF NOT EXISTS ix_standard_change_logs_resource_time ON standard_change_logs (standard_resource_id, detected_at)",
    "CREATE INDEX IF NOT EXISTS ix_standard_change_logs_document_time ON standard_change_logs (document_id, detected_at)",
    "CREATE INDEX IF NOT EXISTS ix_source_status_sync_logs_resource_time ON source_status_sync_logs (standard_resource_id, synced_at)",
    "CREATE INDEX IF NOT EXISTS ix_source_status_sync_logs_document_time ON source_status_sync_logs (document_id, synced_at)",
    "CREATE INDEX IF NOT EXISTS ix_standard_evidence_resource_time ON standard_evidence (standard_resource_id, captured_at)",
    "CREATE INDEX IF NOT EXISTS ix_standard_evidence_document_time ON standard_evidence (document_id, captured_at)",
    "CREATE INDEX IF NOT EXISTS ix_standard_relations_current_no ON standard_relations (current_standard_no, discovered_at)",
    "CREATE INDEX IF NOT EXISTS ix_standard_relations_related_no ON standard_relations (related_standard_no, discovered_at)",
    "CREATE INDEX IF NOT EXISTS ix_standard_relations_current_resource ON standard_relations (current_standard_resource_id, discovered_at)",
    "CREATE INDEX IF NOT EXISTS ix_standard_relations_related_resource ON standard_relations (related_standard_resource_id, discovered_at)",
    "CREATE INDEX IF NOT EXISTS ix_collection_tasks_status_id ON collection_tasks (status, id)",
]


def run_lightweight_migrations() -> None:
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    with engine.begin() as connection:
        for ddl in SQLITE_TABLES:
            connection.execute(text(ddl))
        for table_name, columns in SQLITE_COLUMNS.items():
            if table_name not in inspector.get_table_names():
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, ddl in columns.items():
                if column_name not in existing:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
        for ddl in SQLITE_INDEXES:
            connection.execute(text(ddl))
