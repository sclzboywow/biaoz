from datetime import date, datetime
from enum import Enum

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SourceStatus(str, Enum):
    normal = "正常"
    invalid = "失效"
    login_required = "需登录"
    error = "异常"


class ValidStatus(str, Enum):
    active = "现行"
    abolished = "废止"
    replaced = "替代"
    pending = "待确认"
    reference = "参考"


class ChangeType(str, Enum):
    created = "新增"
    updated = "更新"
    unchanged = "无变化"


class AlertLevel(str, Enum):
    high = "高"
    medium = "中"
    low = "低"


class AlertStatus(str, Enum):
    pending = "未处理"
    handled = "已处理"
    ignored = "忽略"


class ReviewStatus(str, Enum):
    pending = "待复核"
    confirmed = "已确认"
    abolished = "已废止"
    reference = "仅参考"


class UrlSource(TimestampMixin, Base):
    __tablename__ = "url_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source_name: Mapped[str | None] = mapped_column(String(255))
    source_unit: Mapped[str | None] = mapped_column(String(255))
    source_type: Mapped[str | None] = mapped_column(String(80))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    category: Mapped[str | None] = mapped_column(String(120))
    check_frequency: Mapped[str | None] = mapped_column(String(80), default="daily")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default=SourceStatus.normal.value)
    error_message: Mapped[str | None] = mapped_column(Text)
    remark: Mapped[str | None] = mapped_column(Text)
    host: Mapped[str | None] = mapped_column(String(255), index=True)
    url_type: Mapped[str | None] = mapped_column(String(40), index=True)
    file_ext: Mapped[str | None] = mapped_column(String(20), index=True)
    is_official_domain: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_cloud_drive: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_probable_pdf: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_probable_detail_page: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source_quality_score: Mapped[int | None] = mapped_column(Integer, index=True)
    governance_status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    duplicate_group_key: Mapped[str | None] = mapped_column(String(64), index=True)

    versions: Mapped[list["DocumentVersion"]] = relationship(back_populates="url_source")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="url_source")
    category_ref: Mapped["Category | None"] = relationship()


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    standard_no: Mapped[str | None] = mapped_column(String(120), index=True)
    raw_standard_no: Mapped[str | None] = mapped_column(String(160), index=True)
    normalized_standard_no: Mapped[str | None] = mapped_column(String(160), index=True)
    standard_prefix: Mapped[str | None] = mapped_column(String(40), index=True)
    standard_main_no: Mapped[str | None] = mapped_column(String(80), index=True)
    standard_year: Mapped[str | None] = mapped_column(String(10), index=True)
    standard_revision_note: Mapped[str | None] = mapped_column(String(255))
    source_status: Mapped[str | None] = mapped_column(String(80), index=True)
    system_status: Mapped[str | None] = mapped_column(String(80), index=True)
    manual_status: Mapped[str | None] = mapped_column(String(80), index=True)
    doc_type: Mapped[str | None] = mapped_column(String(50))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    category: Mapped[str | None] = mapped_column(String(120))
    issuing_authority: Mapped[str | None] = mapped_column(String(255))
    publish_date: Mapped[date | None] = mapped_column(Date)
    effective_date: Mapped[date | None] = mapped_column(Date)
    valid_status: Mapped[str] = mapped_column(String(30), default=ValidStatus.pending.value)
    review_status: Mapped[str] = mapped_column(String(30), default=ReviewStatus.pending.value)
    metadata_status: Mapped[str] = mapped_column(String(30), default="系统识别")
    current_version_id: Mapped[int | None] = mapped_column(Integer)
    review_remark: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[str | None] = mapped_column(Text)

    versions: Mapped[list["DocumentVersion"]] = relationship(back_populates="document")
    project_links: Mapped[list["ProjectDocument"]] = relationship(back_populates="document")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="document")
    category_ref: Mapped["Category | None"] = relationship()


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False)
    url_source_id: Mapped[int | None] = mapped_column(ForeignKey("url_sources.id"))
    version_no: Mapped[str | None] = mapped_column(String(80))
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_object_id: Mapped[int | None] = mapped_column(ForeignKey("file_objects.id"), index=True)
    original_file_name: Mapped[str | None] = mapped_column(String(500))
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    content_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    change_type: Mapped[str] = mapped_column(String(30), default=ChangeType.created.value)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    remark: Mapped[str | None] = mapped_column(Text)

    document: Mapped["Document"] = relationship(back_populates="versions")
    url_source: Mapped["UrlSource | None"] = relationship(back_populates="versions")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    project_type: Mapped[str | None] = mapped_column(String(120))
    owner_unit: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str | None] = mapped_column(String(80))
    remark: Mapped[str | None] = mapped_column(Text)

    document_links: Mapped[list["ProjectDocument"]] = relationship(back_populates="project")


class ProjectDocument(Base):
    __tablename__ = "project_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False)
    usage_type: Mapped[str | None] = mapped_column(String(80))
    importance: Mapped[str | None] = mapped_column(String(50))
    confirmed_by: Mapped[str | None] = mapped_column(String(120))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remark: Mapped[str | None] = mapped_column(Text)

    project: Mapped["Project"] = relationship(back_populates="document_links")
    document: Mapped["Document"] = relationship(back_populates="project_links")


class CheckLog(Base):
    __tablename__ = "check_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    url_source_id: Mapped[int] = mapped_column(ForeignKey("url_sources.id"), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    check_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_code: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[str | None] = mapped_column(String(80))
    change_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    url_source_id: Mapped[int | None] = mapped_column(ForeignKey("url_sources.id"))
    alert_type: Mapped[str] = mapped_column(String(80), nullable=False)
    alert_level: Mapped[str] = mapped_column(String(30), default=AlertLevel.medium.value)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=AlertStatus.pending.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handled_by: Mapped[str | None] = mapped_column(String(120))
    dedupe_key: Mapped[str | None] = mapped_column(String(128), index=True)
    repeat_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    risk_level: Mapped[str | None] = mapped_column(String(20), index=True)

    document: Mapped["Document | None"] = relationship(back_populates="alerts")
    url_source: Mapped["UrlSource | None"] = relationship(back_populates="alerts")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    parent_id: Mapped[int | None] = mapped_column(Integer)
    category_name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="启用")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tag_name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    tag_type: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentTag(Base):
    __tablename__ = "document_tags"

    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(30), default="string")
    label: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TrustedSource(TimestampMixin, Base):
    __tablename__ = "trusted_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    trust_level: Mapped[str] = mapped_column(String(30), default="A")
    trust_score: Mapped[int] = mapped_column(Integer, default=100)
    source_type: Mapped[str] = mapped_column(String(120), default="标准规范可信目录源")
    adapter_key: Mapped[str | None] = mapped_column(String(120))
    capabilities: Mapped[str | None] = mapped_column(Text)
    is_status_authority: Mapped[bool] = mapped_column(Boolean, default=True)
    crawl_mode: Mapped[str | None] = mapped_column(String(120))
    crawl_frequency: Mapped[str | None] = mapped_column(String(80), default="weekly")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    remark: Mapped[str | None] = mapped_column(Text)
    source_role: Mapped[str | None] = mapped_column(String(40), index=True)
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    status_authority_weight: Mapped[int | None] = mapped_column(Integer)
    fulltext_weight: Mapped[int | None] = mapped_column(Integer)
    metadata_weight: Mapped[int | None] = mapped_column(Integer)
    source_health_score: Mapped[int | None] = mapped_column(Integer, index=True)
    governance_status: Mapped[str] = mapped_column(String(40), default="pending", index=True)


class SourceCategory(Base):
    __tablename__ = "source_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("trusted_sources.id"), nullable=False)
    source_category_id: Mapped[str | None] = mapped_column(String(120))
    parent_id: Mapped[int | None] = mapped_column(Integer)
    category_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category_path: Mapped[str | None] = mapped_column(Text)
    resource_count: Mapped[int | None] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_status: Mapped[str | None] = mapped_column(String(80), default="待同步")
    last_sync_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    last_synced_page: Mapped[int | None] = mapped_column(Integer)
    last_seen_book_ids_hash: Mapped[str | None] = mapped_column(String(128))


class StandardResource(TimestampMixin, Base):
    __tablename__ = "standard_resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("trusted_sources.id"), nullable=False)
    source_book_id: Mapped[str | None] = mapped_column(String(120), index=True)
    source_name: Mapped[str | None] = mapped_column(String(120))
    standard_no: Mapped[str | None] = mapped_column(String(120), index=True)
    raw_standard_no: Mapped[str | None] = mapped_column(String(160), index=True)
    normalized_standard_no: Mapped[str | None] = mapped_column(String(160), index=True)
    standard_prefix: Mapped[str | None] = mapped_column(String(40), index=True)
    standard_main_no: Mapped[str | None] = mapped_column(String(80), index=True)
    standard_year: Mapped[str | None] = mapped_column(String(10), index=True)
    standard_revision_note: Mapped[str | None] = mapped_column(String(255))
    source_status_raw: Mapped[str | None] = mapped_column(String(160))
    standard_name: Mapped[str] = mapped_column(String(500), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(120), index=True)
    source_status: Mapped[str | None] = mapped_column(String(80), index=True)
    system_status: Mapped[str | None] = mapped_column(String(80), index=True)
    manual_status: Mapped[str | None] = mapped_column(String(80))
    publish_date: Mapped[date | None] = mapped_column(Date)
    effective_date: Mapped[date | None] = mapped_column(Date)
    abolish_date: Mapped[date | None] = mapped_column(Date)
    storage_date: Mapped[date | None] = mapped_column(Date)
    chief_editor_unit: Mapped[str | None] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[str | None] = mapped_column(Text)
    source_category_path: Mapped[str | None] = mapped_column(Text)
    detail_url: Mapped[str | None] = mapped_column(Text)
    pdf_trial_url: Mapped[str | None] = mapped_column(Text)
    detail_hash: Mapped[str | None] = mapped_column(String(128))
    source_confidence: Mapped[int] = mapped_column(Integer, default=100)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_status: Mapped[str | None] = mapped_column(String(80))
    matched_document_count: Mapped[int] = mapped_column(Integer, default=0)
    auto_decision: Mapped[str | None] = mapped_column(String(40), index=True)
    confidence_score: Mapped[int | None] = mapped_column(Integer, index=True)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str | None] = mapped_column(String(20), index=True)
    last_governed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class StandardDetail(Base):
    __tablename__ = "standard_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    standard_resource_id: Mapped[int] = mapped_column(ForeignKey("standard_resources.id"), nullable=False)
    catalog_text: Mapped[str | None] = mapped_column(Text)
    mandatory_provisions: Mapped[str | None] = mapped_column(Text)
    expert_interpretation: Mapped[str | None] = mapped_column(Text)
    product_info: Mapped[str | None] = mapped_column(Text)
    change_info: Mapped[str | None] = mapped_column(Text)
    related_books: Mapped[str | None] = mapped_column(Text)
    raw_html_path: Mapped[str | None] = mapped_column(Text)
    raw_text_path: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StandardEvidence(Base):
    __tablename__ = "standard_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    standard_resource_id: Mapped[int | None] = mapped_column(ForeignKey("standard_resources.id"))
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    source_name: Mapped[str | None] = mapped_column(String(120))
    source_level: Mapped[str | None] = mapped_column(String(30))
    source_url: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    raw_status_text: Mapped[str | None] = mapped_column(String(160))
    parsed_status: Mapped[str | None] = mapped_column(String(80))
    page_summary: Mapped[str | None] = mapped_column(Text)
    page_html_hash: Mapped[str | None] = mapped_column(String(128))
    evidence_note: Mapped[str | None] = mapped_column(Text)


class StandardRelation(Base):
    __tablename__ = "standard_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    current_standard_resource_id: Mapped[int | None] = mapped_column(ForeignKey("standard_resources.id"))
    related_standard_resource_id: Mapped[int | None] = mapped_column(ForeignKey("standard_resources.id"))
    current_standard_no: Mapped[str | None] = mapped_column(String(160), index=True)
    related_standard_no: Mapped[str | None] = mapped_column(String(160), index=True)
    relation_type: Mapped[str] = mapped_column(String(80), default="相关")
    relation_text: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_manual_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class StandardFileMatch(Base):
    __tablename__ = "standard_file_matches"
    __table_args__ = (UniqueConstraint("standard_resource_id", "document_id", name="uq_standard_file_matches_resource_document"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    standard_resource_id: Mapped[int] = mapped_column(ForeignKey("standard_resources.id"), nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False)
    document_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"))
    match_type: Mapped[str | None] = mapped_column(String(80))
    match_score: Mapped[int | None] = mapped_column(Integer)
    match_reason: Mapped[str | None] = mapped_column(Text)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(80), default="待确认")


class StandardChangeLog(Base):
    __tablename__ = "standard_change_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    standard_resource_id: Mapped[int] = mapped_column(ForeignKey("standard_resources.id"), nullable=False)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    document_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"))
    field_name: Mapped[str] = mapped_column(String(120), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    change_type: Mapped[str | None] = mapped_column(String(80))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_url: Mapped[str | None] = mapped_column(Text)
    handled_status: Mapped[str] = mapped_column(String(80), default="未处理")
    evidence_summary: Mapped[str | None] = mapped_column(Text)


class SourceStatusSyncLog(Base):
    __tablename__ = "source_status_sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    standard_resource_id: Mapped[int] = mapped_column(ForeignKey("standard_resources.id"), nullable=False)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    old_status: Mapped[str | None] = mapped_column(String(80))
    new_status: Mapped[str | None] = mapped_column(String(80))
    sync_action: Mapped[str | None] = mapped_column(String(120))
    sync_reason: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WpsStandardQueryRecord(TimestampMixin, Base):
    """WPS 多维表「标准查询系统」原始快照，供后续数据治理。"""

    __tablename__ = "wps_standard_query_records"
    __table_args__ = (UniqueConstraint("wps_record_id", name="uq_wps_standard_query_records_wps_record_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    wps_record_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    serial_no: Mapped[int | None] = mapped_column(Integer, index=True)
    file_no: Mapped[str | None] = mapped_column(Text, index=True)
    file_name: Mapped[str | None] = mapped_column(Text)
    impl_status: Mapped[str | None] = mapped_column(String(80), index=True)
    link_url: Mapped[str | None] = mapped_column(Text)
    goto_url: Mapped[str | None] = mapped_column(Text)
    fields_json: Mapped[str] = mapped_column(Text, nullable=False)
    wps_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_sheet: Mapped[str] = mapped_column(String(120), default="标准查询系统")
    governance_status: Mapped[str] = mapped_column(String(40), default="pending", index=True)


class SourceGovernanceRun(TimestampMixin, Base):
    __tablename__ = "source_governance_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
    config_json: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceRecordCandidate(TimestampMixin, Base):
    __tablename__ = "source_record_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("source_governance_runs.id"), nullable=False, index=True)
    url_source_id: Mapped[int | None] = mapped_column(ForeignKey("url_sources.id"), index=True)
    trusted_source_id: Mapped[int | None] = mapped_column(ForeignKey("trusted_sources.id"), index=True)
    candidate_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    host: Mapped[str | None] = mapped_column(String(255), index=True)
    url_type: Mapped[str | None] = mapped_column(String(40), index=True)
    quality_score: Mapped[int | None] = mapped_column(Integer, index=True)
    duplicate_group_key: Mapped[str | None] = mapped_column(String(64), index=True)
    governance_status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    evidence_json: Mapped[str | None] = mapped_column(Text)


class GovernanceDecision(Base):
    __tablename__ = "governance_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("source_governance_runs.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    confidence_score: Mapped[int | None] = mapped_column(Integer, index=True)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    evidence_count: Mapped[int | None] = mapped_column(Integer)
    highest_source_level: Mapped[str | None] = mapped_column(String(30))
    highest_source_weight: Mapped[int | None] = mapped_column(Integer)
    conflict_count: Mapped[int | None] = mapped_column(Integer)
    risk_level: Mapped[str | None] = mapped_column(String(20), index=True)
    decided_by: Mapped[str | None] = mapped_column(String(120))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    metadata_json: Mapped[str | None] = mapped_column(Text)


class FileObject(Base):
    __tablename__ = "file_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_ext: Mapped[str | None] = mapped_column(String(20))
    mime_type: Mapped[str | None] = mapped_column(String(120))
    storage_backend: Mapped[str | None] = mapped_column(String(40))
    storage_path: Mapped[str | None] = mapped_column(Text)
    baidu_pan_uri: Mapped[str | None] = mapped_column(Text)
    minio_object_key: Mapped[str | None] = mapped_column(Text)
    local_path: Mapped[str | None] = mapped_column(Text)
    pdf_valid: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    pdf_validation_status: Mapped[str | None] = mapped_column(String(40))
    pdf_page_count: Mapped[int | None] = mapped_column(Integer)
    pdf_title: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OcrDownloadTask(TimestampMixin, Base):
    __tablename__ = "ocr_download_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    resource_id: Mapped[int | None] = mapped_column(ForeignKey("standard_resources.id"), index=True)
    url_source_id: Mapped[int | None] = mapped_column(ForeignKey("url_sources.id"), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("trusted_sources.id"), index=True)
    standard_no: Mapped[str | None] = mapped_column(String(120), index=True)
    standard_name: Mapped[str | None] = mapped_column(String(500))
    download_url: Mapped[str | None] = mapped_column(Text)
    captcha_url: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    last_error: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    locked_by: Mapped[str | None] = mapped_column(String(120))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("governance_decisions.id"), index=True)
    file_object_id: Mapped[int | None] = mapped_column(ForeignKey("file_objects.id"), index=True)
    host: Mapped[str | None] = mapped_column(String(255), index=True)


class ProcessAuditLog(Base):
    __tablename__ = "process_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    process_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(40), index=True)
    target_id: Mapped[int | None] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(40), default="ok", index=True)
    message: Mapped[str | None] = mapped_column(Text)
    detail_json: Mapped[str | None] = mapped_column(Text)
    process_type: Mapped[str | None] = mapped_column(String(80), index=True)
    step_name: Mapped[str | None] = mapped_column(String(80), index=True)
    source_id: Mapped[int | None] = mapped_column(Integer, index=True)
    confidence_score: Mapped[int | None] = mapped_column(Integer)
    input_summary: Mapped[str | None] = mapped_column(Text)
    output_summary: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class CollectionTask(TimestampMixin, Base):
    __tablename__ = "collection_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_type: Mapped[str] = mapped_column(String(80), default="url_check")
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
    include_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    batch_size: Mapped[int] = mapped_column(Integer, default=50)
    last_source_id: Mapped[int | None] = mapped_column(Integer)
    worker_id: Mapped[str | None] = mapped_column(String(120))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LocalFileIntakeTask(TimestampMixin, Base):
    __tablename__ = "local_file_intake_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    original_file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    temp_file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(40))
    mime_type: Mapped[str | None] = mapped_column(String(120))
    page_count: Mapped[int | None] = mapped_column(Integer)
    extracted_text_sample: Mapped[str | None] = mapped_column(Text)
    extracted_standard_no: Mapped[str | None] = mapped_column(String(160), index=True)
    normalized_standard_no: Mapped[str | None] = mapped_column(String(160), index=True)
    extracted_title: Mapped[str | None] = mapped_column(String(500))
    extracted_publish_date: Mapped[date | None] = mapped_column(Date)
    extracted_effective_date: Mapped[date | None] = mapped_column(Date)
    recognition_status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    decision: Mapped[str | None] = mapped_column(String(40), index=True)
    confidence_score: Mapped[int | None] = mapped_column(Integer)
    risk_level: Mapped[str | None] = mapped_column(String(20))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    final_action: Mapped[str | None] = mapped_column(String(40))
    linked_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), index=True)
    linked_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"), index=True)

    candidates: Mapped[list["LocalFileRecognitionCandidate"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    logs: Mapped[list["LocalFileIntakeLog"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class LocalFileRecognitionCandidate(Base):
    __tablename__ = "local_file_recognition_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("local_file_intake_tasks.id"), nullable=False, index=True)
    candidate_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    candidate_id: Mapped[int | None] = mapped_column(Integer, index=True)
    source_id: Mapped[int | None] = mapped_column(Integer, index=True)
    source_name: Mapped[str | None] = mapped_column(String(255))
    standard_no: Mapped[str | None] = mapped_column(String(160))
    normalized_standard_no: Mapped[str | None] = mapped_column(String(160))
    standard_name: Mapped[str | None] = mapped_column(String(500))
    source_status: Mapped[str | None] = mapped_column(String(80))
    publish_date: Mapped[date | None] = mapped_column(Date)
    effective_date: Mapped[date | None] = mapped_column(Date)
    abolish_date: Mapped[date | None] = mapped_column(Date)
    detail_url: Mapped[str | None] = mapped_column(Text)
    pdf_trial_url: Mapped[str | None] = mapped_column(Text)
    match_score: Mapped[int] = mapped_column(Integer, default=0)
    match_reason: Mapped[str | None] = mapped_column(Text)
    decision_advice: Mapped[str | None] = mapped_column(String(40))
    search_backend: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped["LocalFileIntakeTask"] = relationship(back_populates="candidates")


class LocalFileIntakeLog(Base):
    __tablename__ = "local_file_intake_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("local_file_intake_tasks.id"), nullable=False, index=True)
    step_name: Mapped[str] = mapped_column(String(80), nullable=False)
    result: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    detail_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    task: Mapped["LocalFileIntakeTask"] = relationship(back_populates="logs")


class CertificationRecord(TimestampMixin, Base):
    __tablename__ = "certification_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("trusted_sources.id"), nullable=False, index=True)
    source_item_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    record_type: Mapped[str | None] = mapped_column(String(120), index=True)
    org_name: Mapped[str | None] = mapped_column(String(500), index=True)
    certificate_no: Mapped[str | None] = mapped_column(String(160), index=True)
    standard_refs: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(80), index=True)
    issue_date: Mapped[date | None] = mapped_column(Date)
    expire_date: Mapped[date | None] = mapped_column(Date)
    detail_url: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
