import axios from 'axios'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1',
})

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
}

export type DocumentItem = {
  id: number
  title: string
  standard_no?: string
  doc_type?: string
  category?: string
  valid_status: string
  review_status: string
  metadata_status?: string
  current_version_id?: number
  review_remark?: string
}

export type Alert = {
  id: number
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
}

export type DocumentVersion = {
  id: number
  document_id: number
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

export type StandardResource = {
  id: number
  standard_no?: string
  standard_name: string
  resource_type?: string
  source_status?: string
  system_status?: string
  publish_date?: string
  effective_date?: string
  abolish_date?: string
  source_category_path?: string
  detail_url?: string
  last_synced_at?: string
  matched_document_count?: number
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
  document_version_id?: number
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

export type ResourceChain = {
  resource: StandardResource
  matches: StandardFileMatch[]
  documents: DocumentItem[]
  versions: DocumentVersion[]
  change_logs: StandardChangeLog[]
  sync_logs: SourceStatusSyncLog[]
  alerts: Alert[]
}

export type DocumentChain = {
  document: DocumentItem
  versions: DocumentVersion[]
  matches: StandardFileMatch[]
  resources: StandardResource[]
  change_logs: StandardChangeLog[]
  sync_logs: SourceStatusSyncLog[]
  alerts: Alert[]
}
