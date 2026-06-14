import axios, { type AxiosError } from 'axios'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1',
  timeout: Number(import.meta.env.VITE_API_TIMEOUT_MS || 60_000),
})

api.interceptors.response.use(
  response => response,
  (error: AxiosError<{ detail?: string }>) => {
    const detail = error.response?.data?.detail
    const userMessage = typeof detail === 'string' ? detail : error.message
    return Promise.reject(Object.assign(error, { userMessage }))
  },
)

export type UrlSource = {
  id: number
  url: string
  source_name?: string
  source_unit?: string
  source_type?: string
  category?: string
  error_message?: string
  status: string
  check_frequency?: string
  last_checked_at?: string
  host?: string
  url_type?: string
  file_ext?: string
  is_official_domain?: boolean
  is_cloud_drive?: boolean
  is_probable_pdf?: boolean
  is_probable_detail_page?: boolean
  source_quality_score?: number
  governance_status?: string
  duplicate_group_key?: string
}

export type UrlCheckResult = {
  source_id: number
  url: string
  ok: boolean
  status_code?: number
  result: string
  message: string
  document_id?: number
  version_id?: number
  alert_id?: number
  file_hash?: string
  change_type?: string
}

export type DocumentItem = {
  id: number
  title: string
  standard_no?: string
  raw_standard_no?: string
  normalized_standard_no?: string
  standard_prefix?: string
  standard_main_no?: string
  standard_year?: string
  standard_revision_note?: string
  source_status?: string
  system_status?: string
  manual_status?: string
  doc_type?: string
  category?: string
  valid_status: string
  review_status: string
  metadata_status?: string
  classification_decision?: string | null
  classification_confidence_score?: number | null
  classification_risk_level?: string | null
  classification_reason?: string | null
  standard_level?: string | null
  current_version_id?: number
  review_remark?: string
}

export type Alert = {
  id: number
  document_id?: number
  url_source_id?: number
  alert_type: string
  alert_level: string
  message: string
  status: string
  created_at: string
  handled_at?: string
  handled_by?: string
}

export type Page<T> = {
  total: number
  items: T[]
  next_cursor?: number
  has_more?: boolean
}

export type DocumentVersion = {
  id: number
  document_id: number
  document_title?: string
  standard_no?: string
  url_source_id?: number
  version_no?: string
  file_name: string
  file_path: string
  file_hash: string
  file_size: number
  downloaded_at: string
  change_type: string
  is_current: boolean
}

export type SystemSetting = {
  key: string
  value?: string
  value_type: string
  label?: string
  description?: string
  updated_at?: string
}

export type StorageStatus = {
  root: string
  available: boolean
  exists: boolean
  is_dir: boolean
  writable: boolean
  auto_create: boolean
  pause_download_if_unavailable: boolean
  message: string
}

export type StorageDirectoryItem = {
  name: string
  path: string
}

export type StorageBrowse = {
  path?: string
  parent?: string
  directories: StorageDirectoryItem[]
}

export type CollectionTask = {
  id: number
  task_type: string
  status: string
  total: number
  processed: number
  success: number
  failed: number
  include_manual?: boolean
  batch_size?: number
  last_source_id?: number
  worker_id?: string
  heartbeat_at?: string
  message?: string
  started_at?: string
  finished_at?: string
  created_at: string
  updated_at?: string
}

export type LocalFileIntakeTask = {
  id: number
  original_file_name: string
  temp_file_path: string
  file_hash: string
  file_size: number
  file_type?: string | null
  mime_type?: string | null
  page_count?: number | null
  extracted_text_sample?: string | null
  extracted_standard_no?: string | null
  normalized_standard_no?: string | null
  extracted_title?: string | null
  extracted_publish_date?: string | null
  extracted_effective_date?: string | null
  recognition_status: string
  decision?: string | null
  confidence_score?: number | null
  risk_level?: string | null
  decision_reason?: string | null
  reviewed_by?: string | null
  reviewed_at?: string | null
  final_action?: string | null
  linked_document_id?: number | null
  linked_version_id?: number | null
  created_at: string
  updated_at?: string | null
}

export type LocalFileRecognitionCandidate = {
  id: number
  task_id: number
  candidate_type: string
  candidate_id?: number | null
  source_id?: number | null
  source_name?: string | null
  standard_no?: string | null
  normalized_standard_no?: string | null
  standard_name?: string | null
  source_status?: string | null
  publish_date?: string | null
  effective_date?: string | null
  abolish_date?: string | null
  detail_url?: string | null
  pdf_trial_url?: string | null
  match_score: number
  match_reason?: string | null
  decision_advice?: string | null
  search_backend?: string | null
  created_at: string
}

export type LocalFileIntakeLog = {
  id: number
  task_id: number
  step_name: string
  result: string
  message?: string | null
  detail_json?: string | null
  created_at: string
}

export type LocalFileIntakeDetail = {
  task: LocalFileIntakeTask
  candidates: LocalFileRecognitionCandidate[]
  logs: LocalFileIntakeLog[]
}

export type LocalFileIntakeExternalSearchResponse = LocalFileIntakeDetail & {
  added: number
  errors: TrustedSourceSearchError[]
}

export type TrustedSourceSearchError = {
  source_id: number
  source_name: string
  adapter_key?: string | null
  message: string
}

export type LocalFileIntakePage = {
  total: number
  items: LocalFileIntakeTask[]
  next_cursor?: number | null
  has_more?: boolean
}

export type LocalFileIntakeConfirmPayload = {
  action: 'ignore' | 'link_existing' | 'new_version' | 'create_document' | 'mark_review'
  document_id?: number
  standard_resource_id?: number
  candidate_id?: number
  reviewed_by?: string
  remark?: string
}

export type IngestRuntimeWorker = {
  key: string
  name: string
  group: string
  status: string
  status_message: string
  pid?: number | null
  pid_alive?: boolean | null
  cursor?: string | null
  last_exit?: number | null
  last_started?: string | null
  last_finished?: string | null
  log_mtime?: string | null
  log_file: string
  pid_file: string
  summary?: Record<string, unknown> | null
  upload_summary?: Record<string, unknown> | null
  tail: string[]
}

export type IngestRuntimeChannel = {
  channel: string
  total: number
  recent: number
  on_baidu: number
}

export type IngestRuntimeSummary = {
  reported_at: string
  interval_minutes: number
  log_root: string
  status_counts: Record<string, number>
  database: {
    totals: Record<string, number>
    channels: IngestRuntimeChannel[]
  }
  workers: IngestRuntimeWorker[]
}

export type TrustedSource = {
  id: number
  source_name: string
  base_url: string
  trust_level: string
  trust_score: number
  source_type: string
  adapter_key?: string
  capabilities?: string
  is_status_authority: boolean
  crawl_mode?: string
  crawl_frequency?: string
  enabled: boolean
  remark?: string
  source_role?: string
  domain?: string
  status_authority_weight?: number
  fulltext_weight?: number
  metadata_weight?: number
  source_health_score?: number
  governance_status?: string
}

export type SourceGovernanceRun = {
  id: number
  run_type: string
  status: string
  total: number
  processed: number
  success: number
  failed: number
  message?: string
  config_json?: string
  started_at?: string
  finished_at?: string
  created_at: string
  updated_at?: string
}

export type GovernanceSummary = {
  total: number
  profiled: number
  unprofiled: number
  official_count: number
  pdf_count: number
  cloud_drive_count: number
  duplicate_count: number
  invalid_count: number
  need_ocr_count: number
  high_priority_count: number
  clue_only_count: number
  blacklist_candidate_count: number
  url_sources: Record<string, number>
  trusted_sources: Record<string, number>
  recent_runs: Array<{
    id: number
    run_type: string
    status: string
    total: number
    success: number
    failed: number
    message?: string
    started_at?: string
    finished_at?: string
  }>
}

export type ProfileUrlSourcesResult = {
  run_id?: number | null
  total: number
  profiled: number
  official_count: number
  pdf_count: number
  cloud_drive_count: number
  duplicate_count: number
  invalid_count: number
  need_ocr_count: number
  high_priority_count: number
  clue_only_count: number
  blacklist_candidate_count: number
  dry_run: boolean
}

export type SampleRunResult = ProfileUrlSourcesResult & {
  sample_type: string
  scanned: number
}

export type RunDecisionsResult = {
  processed: number
  auto_confirmed: number
  auto_merged: number
  auto_downgraded: number
  auto_rejected: number
  need_review: number
  high_risk_count: number
  conflict_count: number
  dry_run: boolean
  run_id?: number | null
}

export type GovernanceExceptionItem = {
  decision_id: number
  resource_id: number
  standard_no?: string | null
  standard_name: string
  exception_type: string
  risk_level?: string | null
  highest_source_level?: string | null
  highest_source_weight?: number | null
  conflict_sources?: string[]
  system_suggestion?: string | null
  handle_status: string
  confidence_score?: number | null
  conflict_count?: number
  decided_at?: string | null
}

export type GovernanceExceptionPage = {
  total: number
  items: GovernanceExceptionItem[]
  next_cursor?: number | null
  has_more: boolean
}

export type GovernanceSupervisionSummary = {
  pending_exceptions: number
  high_risk_exceptions: number
  auto_confirmed: number
  auto_merged: number
  auto_downgraded: number
  pending_alerts: number
  recent_runs: Array<{
    id: number
    run_type: string
    status: string
    total: number
    success: number
    failed: number
    message?: string
    finished_at?: string
  }>
}

export type OcrTaskDashboard = {
  pending: number
  running: number
  success_today: number
  ocr_success_rate: number
  pdf_pass_rate: number
  failed: number
  need_manual: number
}

export type OcrDownloadTask = {
  id: number
  resource_id?: number | null
  standard_no?: string | null
  standard_name?: string | null
  provider?: string | null
  status: string
  priority: number
  attempt_count: number
  max_attempts: number
  last_error?: string | null
  next_retry_at?: string | null
  finished_at?: string | null
  created_at?: string | null
}

export type OcrDownloadTaskPage = {
  total: number
  items: OcrDownloadTask[]
  next_cursor?: number | null
  has_more: boolean
}

export type FileObjectItem = {
  id: number
  file_hash: string
  file_size: number
  pdf_valid: boolean
  pdf_validation_status?: string | null
  pdf_page_count?: number | null
  storage_backend?: string | null
  local_path?: string | null
  linked_standard_count: number
  linked_source_count: number
  created_at?: string | null
}

export type FileObjectPage = {
  total: number
  items: FileObjectItem[]
  next_cursor?: number | null
  has_more: boolean
}

export type GovernanceDashboardSummary = {
  url_total: number
  profiled_url_count: number
  ungoverned_url_count: number
  official_source_count: number
  low_trust_source_count: number
  duplicate_url_count: number
  invalid_url_count: number
  need_ocr_count: number
  auto_confirmed_count: number
  need_manual_count: number
  ocr_success_today: number
  pdf_invalid_today: number
  auto_merged_count?: number
  auto_downgraded_count?: number
  pending_alerts?: number
  distributions: {
    url_type?: Record<string, number>
    source_quality?: Record<string, number>
    governance_status?: Record<string, number>
    risk?: Record<string, number>
  }
}

export type SourceHealthItem = {
  id: number
  source_name: string
  source_role?: string | null
  trust_level: string
  domain?: string | null
  health_score: number
  capture_success_rate: number
  number_parse_rate: number
  status_parse_rate: number
  pdf_valid_rate: number
  ocr_success_rate: number
  duplicate_rate: number
  conflict_rate: number
  governance_status: string
  enabled: boolean
  url_count: number
  resource_count: number
  need_ocr_count: number
  suggested_action: string
}

export type SourceHealthPage = {
  total: number
  items: SourceHealthItem[]
  next_cursor?: number | null
  has_more: boolean
}

export type OcrTasksSummary = {
  pending_ocr: number
  running: number
  archived: number
  ocr_failed: number
  captcha_failed: number
  download_failed: number
  pdf_invalid: number
  duplicate_file: number
  skipped: number
  need_manual: number
  success_today: number
  ocr_success_rate_today: number
  pdf_pass_rate_today: number
  pending?: number
  failed?: number
  ocr_success_rate?: number
  pdf_pass_rate?: number
}

export type FileObjectsSummary = {
  total: number
  pdf_valid: number
  pdf_invalid: number
  duplicate_hint: number
  large_files: number
  unlinked: number
}

export type SupervisionSummaryEnhanced = GovernanceSupervisionSummary & {
  auto_rejected: number
  status_conflict_count: number
  file_anomaly_count: number
  ocr_anomaly_count: number
  need_review_count: number
}

export type ProcessAuditLog = {
  id: number
  process_name: string
  process_type?: string | null
  step_name?: string | null
  action: string
  target_type?: string | null
  target_id?: number | null
  source_id?: number | null
  status: string
  message?: string | null
  confidence_score?: number | null
  input_summary?: string | null
  output_summary?: string | null
  error_message?: string | null
  created_at?: string | null
}

export type SourceCategory = {
  id: number
  source_id: number
  source_category_id?: string
  parent_id?: number
  category_name: string
  category_path?: string
  resource_count?: number
  source_url?: string
  last_synced_at?: string
  sync_status?: string
  last_sync_started_at?: string
  last_sync_finished_at?: string
  last_sync_error?: string
  last_synced_page?: number
  last_seen_book_ids_hash?: string
}

export type RawRecord = {
  id: number
  wps_record_id: string
  serial_no?: number | null
  file_no?: string | null
  file_name?: string | null
  impl_status?: string | null
  link_url?: string | null
  goto_url?: string | null
  fields_json: string
  wps_fetched_at?: string | null
  source_sheet: string
  governance_status: string
  created_at: string
  updated_at?: string | null
}

export type StandardResource = {
  id: number
  standard_no?: string
  raw_standard_no?: string
  normalized_standard_no?: string
  standard_prefix?: string
  standard_main_no?: string
  standard_year?: string
  standard_revision_note?: string
  source_status_raw?: string
  standard_name: string
  resource_type?: string
  source_status?: string
  system_status?: string
  publish_date?: string
  effective_date?: string
  abolish_date?: string
  source_category_path?: string
  detail_url?: string
  pdf_trial_url?: string
  last_synced_at?: string
  matched_document_count?: number
  auto_decision?: string | null
  confidence_score?: number | null
  decision_reason?: string | null
  risk_level?: string | null
  last_governed_at?: string | null
  manual_status?: string | null
}

export type ResourceDownloadCaptchaChallenge = {
  resource_id: number
  challenge_id: string
  captcha_image_base64: string
  captcha_content_type: string
  expires_at: string
  message: string
}

export type StandardDetail = {
  id: number
  standard_resource_id: number
  catalog_text?: string
  mandatory_provisions?: string
  expert_interpretation?: string
  product_info?: string
  change_info?: string
  related_books?: string
  raw_html_path?: string
  raw_text_path?: string
  captured_at: string
}

export type StandardFileMatch = {
  id: number
  standard_resource_id: number
  document_id: number
  match_type?: string
  match_score?: number
  match_reason?: string
  matched_at: string
  status: string
}

export type StandardChangeLog = {
  id: number
  standard_resource_id: number
  document_id?: number
  document_title?: string
  document_version_id?: number
  version_no?: string
  file_name?: string
  field_name: string
  old_value?: string
  new_value?: string
  change_type?: string
  detected_at: string
  handled_status: string
  evidence_summary?: string
}

export type SourceStatusSyncLog = {
  id: number
  standard_resource_id: number
  document_id?: number
  old_status?: string
  new_status?: string
  sync_action?: string
  sync_reason?: string
  synced_at: string
}

export type StandardEvidence = {
  id: number
  standard_resource_id?: number
  standard_no?: string | null
  standard_name?: string | null
  document_id?: number
  document_title?: string | null
  source_name?: string
  source_level?: string
  source_url?: string
  captured_at: string
  raw_status_text?: string
  parsed_status?: string
  page_summary?: string
  page_html_hash?: string
  evidence_note?: string
}

export type StandardRelation = {
  id: number
  current_standard_resource_id?: number
  current_standard_name?: string | null
  related_standard_resource_id?: number
  related_standard_name?: string | null
  current_standard_no?: string
  related_standard_no?: string
  relation_type: string
  relation_text?: string
  source_url?: string
  discovered_at: string
  is_manual_confirmed: boolean
}

export type ResourceChain = {
  resource: StandardResource
  details: StandardDetail[]
  matches: StandardFileMatch[]
  documents: DocumentItem[]
  versions: DocumentVersion[]
  url_sources: UrlSource[]
  change_logs: StandardChangeLog[]
  sync_logs: SourceStatusSyncLog[]
  evidences: StandardEvidence[]
  relations: StandardRelation[]
  alerts: Alert[]
  processing_advice?: string
}

export type DocumentChain = {
  document: DocumentItem
  versions: DocumentVersion[]
  matches: StandardFileMatch[]
  resources: StandardResource[]
  url_sources: UrlSource[]
  change_logs: StandardChangeLog[]
  sync_logs: SourceStatusSyncLog[]
  evidences: StandardEvidence[]
  relations: StandardRelation[]
  alerts: Alert[]
  processing_advice?: string
}
