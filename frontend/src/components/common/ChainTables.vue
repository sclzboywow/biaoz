<script setup lang="ts">
import { api, type DocumentVersion } from '../../api'
import {
  changeDocumentFormatter,
  changeEvidenceFormatter,
  changeFieldFormatter,
  changeValueFormatter,
  changeVersionFormatter,
} from '../../utils/changeFormatters'
import { dateTimeFormatter, manualStatusFormatter, sourceStatusFormatter, systemStatusFormatter } from '../../utils/tableFormatters'

defineProps<{
  versions: unknown[]
  urlSources: unknown[]
  syncLogs: unknown[]
  changeLogs: unknown[]
  evidences: unknown[]
  relations: unknown[]
  alerts: unknown[]
}>()

defineEmits<{ 'confirm-relation': [id: number] }>()

function versionFileUrl(versionId: number, inline: boolean) {
  const baseUrl = String(api.defaults.baseURL || '').replace(/\/$/, '')
  return `${baseUrl}/document-versions/${versionId}/file?inline=${inline ? 'true' : 'false'}`
}

function openVersionFile(version: DocumentVersion, inline: boolean) {
  window.open(versionFileUrl(version.id, inline), '_blank', 'noopener')
}
</script>

<template>
  <h3 class="section-title">来源 URL</h3>
  <el-table :data="urlSources" height="180">
    <el-table-column prop="source_name" label="来源名称" width="220" show-overflow-tooltip />
    <el-table-column prop="url" label="URL" min-width="360" show-overflow-tooltip />
    <el-table-column prop="status" label="状态" width="100" />
    <el-table-column prop="last_checked_at" label="最后检查" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
  </el-table>

  <h3 class="section-title">版本记录</h3>
  <el-table :data="versions" height="220">
    <el-table-column prop="version_no" label="版本" width="90" />
    <el-table-column prop="file_name" label="文件名" min-width="280" show-overflow-tooltip />
    <el-table-column prop="change_type" label="变化" width="100" />
    <el-table-column prop="is_current" label="当前" width="90" />
    <el-table-column prop="file_hash" label="文件哈希" min-width="240" show-overflow-tooltip />
    <el-table-column prop="downloaded_at" label="下载时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
    <el-table-column label="文件" width="150" fixed="right">
      <template #default="{ row }">
        <el-button size="small" @click="openVersionFile(row, true)">预览</el-button>
        <el-button size="small" @click="openVersionFile(row, false)">下载</el-button>
      </template>
    </el-table-column>
  </el-table>

  <h3 class="section-title">状态同步记录</h3>
  <el-table :data="syncLogs" height="220">
    <el-table-column prop="old_status" label="原状态" width="140" />
    <el-table-column prop="new_status" label="新状态" width="140" />
    <el-table-column prop="sync_action" label="动作" width="150" />
    <el-table-column prop="sync_reason" label="原因/证据" min-width="420" show-overflow-tooltip />
    <el-table-column prop="synced_at" label="同步时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
  </el-table>

  <h3 class="section-title">变更记录</h3>
  <el-table :data="changeLogs" height="220">
    <el-table-column prop="document_title" label="本地文件" min-width="220" :formatter="changeDocumentFormatter" show-overflow-tooltip />
    <el-table-column prop="version_no" label="版本" min-width="180" :formatter="changeVersionFormatter" show-overflow-tooltip />
    <el-table-column prop="field_name" label="字段" width="150" :formatter="changeFieldFormatter" />
    <el-table-column prop="change_type" label="变化类型" width="130" />
    <el-table-column prop="old_value" label="旧值" min-width="220" :formatter="changeValueFormatter" show-overflow-tooltip />
    <el-table-column prop="new_value" label="新值" min-width="220" :formatter="changeValueFormatter" show-overflow-tooltip />
    <el-table-column prop="evidence_summary" label="证据说明" min-width="260" :formatter="changeEvidenceFormatter" show-overflow-tooltip />
    <el-table-column prop="detected_at" label="发现时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
  </el-table>

  <h3 class="section-title">证据记录</h3>
  <el-table :data="evidences" height="220">
    <el-table-column prop="source_name" label="来源网站" width="160" />
    <el-table-column prop="source_level" label="等级" width="80" />
    <el-table-column prop="raw_status_text" label="原始状态" width="120" />
    <el-table-column prop="parsed_status" label="解析结果" width="140" />
    <el-table-column prop="evidence_note" label="证据说明" min-width="360" show-overflow-tooltip />
    <el-table-column prop="source_url" label="原始 URL" min-width="280" show-overflow-tooltip />
    <el-table-column prop="captured_at" label="抓取时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
  </el-table>

  <h3 class="section-title">替代/相关关系</h3>
  <el-table :data="relations" height="180">
    <el-table-column prop="current_standard_no" label="当前标准" width="160" />
    <el-table-column prop="related_standard_no" label="关联标准" width="160" />
    <el-table-column prop="relation_type" label="关系类型" width="120" />
    <el-table-column prop="relation_text" label="关系原文" min-width="360" show-overflow-tooltip />
    <el-table-column prop="source_url" label="来源 URL" min-width="260" show-overflow-tooltip />
    <el-table-column prop="is_manual_confirmed" label="人工确认" width="100" />
    <el-table-column label="操作" width="110">
      <template #default="{ row }">
        <el-button size="small" :disabled="row.is_manual_confirmed" @click="$emit('confirm-relation', row.id)">确认关系</el-button>
      </template>
    </el-table-column>
  </el-table>

  <h3 class="section-title">提醒记录</h3>
  <el-table :data="alerts" height="180">
    <el-table-column prop="alert_level" label="等级" width="90" />
    <el-table-column prop="alert_type" label="类型" width="140" />
    <el-table-column prop="message" label="消息" min-width="360" show-overflow-tooltip />
    <el-table-column prop="status" label="状态" width="110" />
    <el-table-column prop="created_at" label="创建时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
  </el-table>
</template>
