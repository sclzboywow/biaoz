from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UrlSourceBase(BaseModel):
    url: str
    source_name: str | None = None
    source_unit: str | None = None
    source_type: str | None = None
    category_id: int | None = None
    category: str | None = None
    check_frequency: str | None = "daily"
    status: str | None = "正常"
    error_message: str | None = None
    remark: str | None = None


class UrlSourceCreate(UrlSourceBase):
    pass


class UrlSourceUpdate(BaseModel):
    url: str | None = None
    source_name: str | None = None
    source_unit: str | None = None
    source_type: str | None = None
    category_id: int | None = None
    category: str | None = None
    check_frequency: str | None = None
    status: str | None = None
    error_message: str | None = None
    remark: str | None = None


class UrlSourceOut(UrlSourceBase, OrmModel):
    id: int
    last_checked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class DocumentBase(BaseModel):
    title: str
    standard_no: str | None = None
    raw_standard_no: str | None = None
    normalized_standard_no: str | None = None
    standard_prefix: str | None = None
    standard_main_no: str | None = None
    standard_year: str | None = None
    standard_revision_note: str | None = None
    source_status: str | None = None
    system_status: str | None = None
    manual_status: str | None = None
    doc_type: str | None = None
    category_id: int | None = None
    category: str | None = None
    issuing_authority: str | None = None
    publish_date: date | None = None
    effective_date: date | None = None
    valid_status: str | None = "待确认"
    review_status: str | None = "待复核"
    metadata_status: str | None = "系统识别"
    current_version_id: int | None = None
    review_remark: str | None = None
    summary: str | None = None
    keywords: str | None = None


class DocumentCreate(DocumentBase):
    pass


class DocumentUpdate(BaseModel):
    title: str | None = None
    standard_no: str | None = None
    raw_standard_no: str | None = None
    normalized_standard_no: str | None = None
    standard_prefix: str | None = None
    standard_main_no: str | None = None
    standard_year: str | None = None
    standard_revision_note: str | None = None
    source_status: str | None = None
    system_status: str | None = None
    manual_status: str | None = None
    doc_type: str | None = None
    category_id: int | None = None
    category: str | None = None
    issuing_authority: str | None = None
    publish_date: date | None = None
    effective_date: date | None = None
    valid_status: str | None = None
    review_status: str | None = None
    metadata_status: str | None = None
    current_version_id: int | None = None
    review_remark: str | None = None
    summary: str | None = None
    keywords: str | None = None


class DocumentOut(DocumentBase, OrmModel):
    id: int
    created_at: datetime
    updated_at: datetime | None = None


class ProjectBase(BaseModel):
    project_name: str
    project_type: str | None = None
    owner_unit: str | None = None
    status: str | None = None
    remark: str | None = None


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    project_name: str | None = None
    project_type: str | None = None
    owner_unit: str | None = None
    status: str | None = None
    remark: str | None = None


class ProjectOut(ProjectBase, OrmModel):
    id: int
    created_at: datetime
    updated_at: datetime | None = None


class ProjectDocumentCreate(BaseModel):
    project_id: int
    document_id: int
    usage_type: str | None = None
    importance: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    remark: str | None = None


class ProjectDocumentOut(ProjectDocumentCreate, OrmModel):
    id: int


class DocumentVersionOut(OrmModel):
    id: int
    document_id: int
    document_title: str | None = None
    standard_no: str | None = None
    url_source_id: int | None = None
    version_no: str | None = None
    file_name: str
    file_path: str
    file_hash: str
    file_size: int
    downloaded_at: datetime
    content_hash: str | None = None
    change_type: str
    is_current: bool
    remark: str | None = None


class DocumentVersionPage(BaseModel):
    total: int
    items: list[DocumentVersionOut]
    next_cursor: int | None = None
    has_more: bool = False


class AlertCreate(BaseModel):
    document_id: int | None = None
    url_source_id: int | None = None
    alert_type: str
    alert_level: str = "中"
    message: str
    status: str = "未处理"


class AlertUpdate(BaseModel):
    status: str | None = None
    handled_at: datetime | None = None
    handled_by: str | None = None


class AlertOut(AlertCreate, OrmModel):
    id: int
    created_at: datetime
    handled_at: datetime | None = None
    handled_by: str | None = None


class UploadVersionResponse(DocumentVersionOut):
    duplicate: bool = Field(default=False, description="是否与当前版本 hash 相同")


class UrlCheckResult(BaseModel):
    source_id: int
    url: str
    ok: bool
    status_code: int | None = None
    result: str
    message: str
    document_id: int | None = None
    version_id: int | None = None
    alert_id: int | None = None
    file_hash: str | None = None
    change_type: str | None = None


class ResourceDownloadCaptchaChallenge(BaseModel):
    resource_id: int
    challenge_id: str
    captcha_image_base64: str
    captcha_content_type: str
    expires_at: datetime
    message: str


class ResourceDownloadCaptchaSubmit(BaseModel):
    challenge_id: str
    verify_code: str


class CheckAllResult(BaseModel):
    total: int
    results: list[UrlCheckResult]


class CollectionTaskCreate(BaseModel):
    include_manual: bool = False
    batch_size: int = 50


class CollectionTaskOut(OrmModel):
    id: int
    task_type: str
    status: str
    total: int
    processed: int
    success: int
    failed: int
    message: str | None = None
    include_manual: bool | None = None
    batch_size: int | None = None
    last_source_id: int | None = None
    worker_id: str | None = None
    heartbeat_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class PageResult(BaseModel):
    total: int
    items: list


class UrlSourcePage(BaseModel):
    total: int
    items: list[UrlSourceOut]
    next_cursor: int | None = None
    has_more: bool = False


class DocumentPage(BaseModel):
    total: int
    items: list[DocumentOut]
    next_cursor: int | None = None
    has_more: bool = False


class AlertPage(BaseModel):
    total: int
    items: list[AlertOut]
    next_cursor: int | None = None
    has_more: bool = False


class CheckLogOut(OrmModel):
    id: int
    url_source_id: int
    checked_at: datetime
    check_time: datetime | None = None
    status_code: int | None = None
    result: str | None = None
    change_detected: bool | None = None
    error_message: str | None = None
    message: str | None = None
    created_at: datetime | None = None


class CheckLogPage(BaseModel):
    total: int
    items: list[CheckLogOut]
    next_cursor: int | None = None
    has_more: bool = False


class CategoryCreate(BaseModel):
    parent_id: int | None = None
    category_name: str
    sort_order: int = 0
    status: str = "启用"


class CategoryOut(CategoryCreate, OrmModel):
    id: int


class SystemSettingOut(OrmModel):
    key: str
    value: str | None = None
    value_type: str
    label: str | None = None
    description: str | None = None
    updated_at: datetime | None = None


class SystemSettingUpdate(BaseModel):
    value: str | None = None


class StorageStatusOut(BaseModel):
    root: str
    available: bool
    exists: bool
    is_dir: bool
    writable: bool
    auto_create: bool
    pause_download_if_unavailable: bool
    message: str


class StorageDirectoryItem(BaseModel):
    name: str
    path: str


class StorageBrowseOut(BaseModel):
    path: str | None = None
    parent: str | None = None
    directories: list[StorageDirectoryItem]


class TrustedSourceOut(OrmModel):
    id: int
    source_name: str
    base_url: str
    trust_level: str
    trust_score: int
    source_type: str
    adapter_key: str | None = None
    capabilities: str | None = None
    is_status_authority: bool
    crawl_mode: str | None = None
    crawl_frequency: str | None = None
    enabled: bool
    remark: str | None = None


class SourceCategoryOut(OrmModel):
    id: int
    source_id: int
    source_category_id: str | None = None
    parent_id: int | None = None
    category_name: str
    category_path: str | None = None
    resource_count: int | None = None
    source_url: str | None = None
    last_synced_at: datetime | None = None
    sync_status: str | None = None
    last_sync_started_at: datetime | None = None
    last_sync_finished_at: datetime | None = None
    last_sync_error: str | None = None
    last_synced_page: int | None = None
    last_seen_book_ids_hash: str | None = None


class SourceCategoryPage(BaseModel):
    total: int
    items: list[SourceCategoryOut]
    next_cursor: int | None = None
    has_more: bool = False


class CategoryDiscoveryResult(BaseModel):
    discovered: int
    created: int
    updated: int


class StandardResourceOut(OrmModel):
    id: int
    source_id: int
    source_book_id: str | None = None
    source_name: str | None = None
    standard_no: str | None = None
    raw_standard_no: str | None = None
    normalized_standard_no: str | None = None
    standard_prefix: str | None = None
    standard_main_no: str | None = None
    standard_year: str | None = None
    standard_revision_note: str | None = None
    source_status_raw: str | None = None
    standard_name: str
    resource_type: str | None = None
    source_status: str | None = None
    system_status: str | None = None
    manual_status: str | None = None
    publish_date: date | None = None
    effective_date: date | None = None
    abolish_date: date | None = None
    storage_date: date | None = None
    chief_editor_unit: str | None = None
    summary: str | None = None
    keywords: str | None = None
    source_category_path: str | None = None
    detail_url: str | None = None
    pdf_trial_url: str | None = None
    source_confidence: int
    last_synced_at: datetime | None = None
    sync_status: str | None = None
    matched_document_count: int | None = None


class StandardResourcePage(BaseModel):
    total: int
    items: list[StandardResourceOut]
    next_cursor: int | None = None
    has_more: bool = False


class StandardDetailOut(OrmModel):
    id: int
    standard_resource_id: int
    catalog_text: str | None = None
    mandatory_provisions: str | None = None
    expert_interpretation: str | None = None
    product_info: str | None = None
    change_info: str | None = None
    related_books: str | None = None
    raw_html_path: str | None = None
    raw_text_path: str | None = None
    captured_at: datetime


class StandardFileMatchOut(OrmModel):
    id: int
    standard_resource_id: int
    document_id: int
    document_version_id: int | None = None
    match_type: str | None = None
    match_score: int | None = None
    match_reason: str | None = None
    matched_at: datetime
    status: str


class StandardFileMatchPage(BaseModel):
    total: int
    items: list[StandardFileMatchOut]
    next_cursor: int | None = None
    has_more: bool = False


class StandardChangeLogOut(OrmModel):
    id: int
    standard_resource_id: int
    document_id: int | None = None
    document_title: str | None = None
    document_version_id: int | None = None
    version_no: str | None = None
    file_name: str | None = None
    field_name: str
    old_value: str | None = None
    new_value: str | None = None
    change_type: str | None = None
    detected_at: datetime
    source_url: str | None = None
    handled_status: str
    evidence_summary: str | None = None


class StandardChangeLogPage(BaseModel):
    total: int
    items: list[StandardChangeLogOut]
    next_cursor: int | None = None
    has_more: bool = False


class SourceStatusSyncLogOut(OrmModel):
    id: int
    standard_resource_id: int
    document_id: int | None = None
    old_status: str | None = None
    new_status: str | None = None
    sync_action: str | None = None
    sync_reason: str | None = None
    synced_at: datetime


class SourceStatusSyncLogPage(BaseModel):
    total: int
    items: list[SourceStatusSyncLogOut]
    next_cursor: int | None = None
    has_more: bool = False


class StandardEvidenceOut(OrmModel):
    id: int
    standard_resource_id: int | None = None
    document_id: int | None = None
    source_name: str | None = None
    source_level: str | None = None
    source_url: str | None = None
    captured_at: datetime
    raw_status_text: str | None = None
    parsed_status: str | None = None
    page_summary: str | None = None
    page_html_hash: str | None = None
    evidence_note: str | None = None


class StandardRelationOut(OrmModel):
    id: int
    current_standard_resource_id: int | None = None
    related_standard_resource_id: int | None = None
    current_standard_no: str | None = None
    related_standard_no: str | None = None
    relation_type: str
    relation_text: str | None = None
    source_url: str | None = None
    discovered_at: datetime
    is_manual_confirmed: bool


class StandardRelationUpdate(BaseModel):
    is_manual_confirmed: bool | None = None
    relation_type: str | None = None
    relation_text: str | None = None


class MatchRunResult(BaseModel):
    matched: int
    skipped: int
    processed: int = 0
    next_cursor: int | None = None
    has_more: bool = False


class ResourceChainOut(BaseModel):
    resource: StandardResourceOut
    details: list[StandardDetailOut]
    matches: list[StandardFileMatchOut]
    documents: list[DocumentOut]
    versions: list[DocumentVersionOut]
    url_sources: list[UrlSourceOut]
    change_logs: list[StandardChangeLogOut]
    sync_logs: list[SourceStatusSyncLogOut]
    evidences: list[StandardEvidenceOut]
    relations: list[StandardRelationOut]
    alerts: list[AlertOut]
    processing_advice: str | None = None


class DocumentChainOut(BaseModel):
    document: DocumentOut
    versions: list[DocumentVersionOut]
    matches: list[StandardFileMatchOut]
    resources: list[StandardResourceOut]
    url_sources: list[UrlSourceOut]
    change_logs: list[StandardChangeLogOut]
    sync_logs: list[SourceStatusSyncLogOut]
    evidences: list[StandardEvidenceOut]
    relations: list[StandardRelationOut]
    alerts: list[AlertOut]
    processing_advice: str | None = None


class GuobiaoSyncRequest(BaseModel):
    max_pages_per_sublib: int = 1
    include_detail: bool = True
    sublib_id: int | None = None


class TrustedSourceSyncRequest(BaseModel):
    source_id: int
    max_pages: int = 1
    include_detail: bool = True
    category_id: str | None = None
    only_pending_categories: bool = False
    category_limit: int | None = None


class GuobiaoSyncResult(BaseModel):
    pages: int
    items: int
    created: int
    updated: int
    skipped_existing_detail: int = 0
    categories: int = 0
    errors: int
    matches: int = 0
    sync_logs: int = 0
    alerts: int = 0
    linked_change_logs: int = 0
