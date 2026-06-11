<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Refresh, Search, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, type UploadRequestOptions } from 'element-plus'
import {
  api,
  type LocalFileIntakeConfirmPayload,
  type LocalFileIntakeDetail,
  type LocalFileIntakeExternalSearchResponse,
  type LocalFileIntakePage,
  type LocalFileIntakeTask,
  type LocalFileRecognitionCandidate,
} from '../../api'
import CursorPager from '../../components/governance/CursorPager.vue'
import StatusTag from '../../components/governance/StatusTag.vue'
import { applyPageResult, createCursorPager, nextCursorPage, prevCursorPage, resetCursorPager } from '../../composables/useCursorPager'
import { formatDateTime } from '../../utils/formatters'

const items = ref<LocalFileIntakeTask[]>([])
const total = ref(0)
const loading = ref(false)
const uploading = ref(false)
const analyzingId = ref<number | null>(null)
const pager = createCursorPager()
const query = reactive({ q: '', recognition_status: '', decision: '' })

const detailVisible = ref(false)
const detailLoading = ref(false)
const externalSearching = ref(false)
const detail = ref<LocalFileIntakeDetail | null>(null)
const selectedCandidateId = ref<number | null>(null)
const confirmRemark = ref('')

const decisionLabels: Record<string, string> = {
  duplicate_ignore: '重复忽略',
  link_existing: '关联已有',
  create_document: '新建入库',
  need_review: '待复核',
}

const statusLabels: Record<string, string> = {
  pending: '待识别',
  processing: '识别中',
  completed: '已完成',
  failed: '失败',
  reviewed: '已处理',
}

const candidateTypeLabels: Record<string, string> = {
  document_version: '已有版本',
  document: '已有标准',
  standard_resource: '可信源',
}

const searchBackendLabels: Record<string, string> = {
  local_index: '本地索引',
  external: '外网实时',
}

const stepLabels: Record<string, string> = {
  upload: '上传',
  extract_metadata: '提取元数据',
  match_versions: '版本匹配',
  match_documents: '文件匹配',
  match_resources: '可信源匹配',
  auto_external_search: '自动外网搜索',
  external_search: '外网复核',
  external_search_decision: '联网决策',
  decision: '系统决策',
  analyze: '识别',
}

function formatSize(size: number) {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${size} B`
}

function decisionLabel(value?: string | null) {
  return value ? decisionLabels[value] || value : '-'
}

function statusLabel(value?: string | null) {
  return value ? statusLabels[value] || value : '-'
}

const activeTask = computed(() => detail.value?.task ?? null)
const duplicateDetected = computed(() => activeTask.value?.decision === 'duplicate_ignore')

async function loadItems() {
  loading.value = true
  try {
    const res = await api.get<LocalFileIntakePage>('/local-file-intake/page', {
      params: {
        cursor: pager.cursors[pager.page - 1] ?? undefined,
        page_size: 50,
        q: query.q || undefined,
        recognition_status: query.recognition_status || undefined,
        decision: query.decision || undefined,
      },
    })
    items.value = res.data.items
    total.value = res.data.total
    applyPageResult(pager, res.data)
  } finally {
    loading.value = false
  }
}

async function resetQuery() {
  resetCursorPager(pager)
  await loadItems()
}

async function uploadFile(file: File) {
  uploading.value = true
  try {
    const form = new FormData()
    form.append('file', file)
    const uploadRes = await api.post<LocalFileIntakeTask>('/local-file-intake/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    ElMessage.success(`已创建识别任务 #${uploadRes.data.id}`)
    await analyzeTask(uploadRes.data.id, false)
    await resetQuery()
  } catch (error: any) {
    ElMessage.error(error.userMessage || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function analyzeTask(taskId: number, reloadList = true) {
  analyzingId.value = taskId
  try {
    const res = await api.post<LocalFileIntakeDetail>(`/local-file-intake/${taskId}/analyze`)
    detail.value = res.data
    selectedCandidateId.value = res.data.candidates[0]?.id ?? null
    detailVisible.value = true
    ElMessage.success('识别完成')
    if (reloadList) await loadItems()
  } catch (error: any) {
    ElMessage.error(error.userMessage || '识别失败')
  } finally {
    analyzingId.value = null
  }
}

async function openDetail(taskId: number) {
  detailLoading.value = true
  detailVisible.value = true
  try {
    const res = await api.get<LocalFileIntakeDetail>(`/local-file-intake/${taskId}`)
    detail.value = res.data
    selectedCandidateId.value = res.data.candidates[0]?.id ?? null
  } finally {
    detailLoading.value = false
  }
}

function searchBackendLabel(value?: string | null) {
  if (!value) return '本地索引'
  return searchBackendLabels[value] || value
}

function stepLabel(value?: string | null) {
  return value ? stepLabels[value] || value : '-'
}

async function runExternalSearch() {
  if (!activeTask.value) return
  externalSearching.value = true
  try {
    const res = await api.post<LocalFileIntakeExternalSearchResponse>(
      `/local-file-intake/${activeTask.value.id}/external-search`,
      null,
      { timeout: 120_000 },
    )
    detail.value = res.data
    if (res.data.added > 0) {
      ElMessage.success(`外网复核完成，新增 ${res.data.added} 条候选`)
    } else {
      ElMessage.info('外网复核完成，未发现新的候选')
    }
    if (res.data.errors.length > 0) {
      ElMessage.warning(`部分可信源访问失败：${res.data.errors.map(item => item.source_name).join('、')}`)
    }
  } catch (error: any) {
    ElMessage.error(error.userMessage || '联网复核失败')
  } finally {
    externalSearching.value = false
  }
}

function selectedCandidate(): LocalFileRecognitionCandidate | undefined {
  return detail.value?.candidates.find(item => item.id === selectedCandidateId.value)
}

async function confirmAction(action: LocalFileIntakeConfirmPayload['action']) {
  if (!activeTask.value) return
  const candidate = selectedCandidate()
  const labels: Record<string, string> = {
    ignore: '忽略该文件',
    link_existing: '关联已有 Document',
    new_version: '作为已有 Document 新版本',
    create_document: '新建 Document 并入库',
    mark_review: '标记待复核',
  }
  await ElMessageBox.confirm(`确认执行：${labels[action]}？`, '确认处理', { type: 'warning' })
  try {
    const payload: LocalFileIntakeConfirmPayload = {
      action,
      candidate_id: candidate?.id,
      document_id: candidate?.candidate_type === 'document' ? candidate.candidate_id ?? undefined : undefined,
      standard_resource_id: candidate?.candidate_type === 'standard_resource' ? candidate.candidate_id ?? undefined : undefined,
      remark: confirmRemark.value || undefined,
    }
    await api.post(`/local-file-intake/${activeTask.value.id}/confirm`, payload)
    ElMessage.success('处理成功')
    detailVisible.value = false
    confirmRemark.value = ''
    await loadItems()
  } catch (error: any) {
    ElMessage.error(error.userMessage || '处理失败')
  }
}

async function deleteTask(task: LocalFileIntakeTask) {
  await ElMessageBox.confirm(`删除未入库任务 #${task.id}？`, '删除确认', { type: 'warning' })
  try {
    await api.delete(`/local-file-intake/${task.id}`)
    ElMessage.success('已删除')
    await loadItems()
  } catch (error: any) {
    ElMessage.error(error.userMessage || '删除失败')
  }
}

function handleUploadRequest(options: UploadRequestOptions) {
  void uploadFile(options.file as File)
}

onMounted(loadItems)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>本地文件识别</h2>
      <div class="toolbar-actions">
        <el-button :icon="Refresh" @click="loadItems">刷新</el-button>
      </div>
    </div>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="上传本地文件后先识别再决定是否正式入库。完全重复才会建议忽略；标准号一致但 hash 不同需人工复核。"
      style="margin-bottom: 12px"
    />

    <div v-loading="uploading" class="upload-panel">
      <el-upload
        drag
        class="upload-dropzone"
        :auto-upload="true"
        :show-file-list="false"
        :disabled="uploading"
        :multiple="false"
        accept=".pdf,.doc,.docx,.xls,.xlsx,.zip,.rar,.7z"
        :http-request="handleUploadRequest"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">拖拽文件到此处，或 <em>点击上传</em></div>
        <template #tip><div class="el-upload__tip">文件先进入临时区，不会直接写入文件归档库</div></template>
      </el-upload>
    </div>

    <el-form :inline="true" class="filters" style="margin-top: 16px">
      <el-form-item label="查询">
        <el-input v-model="query.q" clearable placeholder="文件名 / 标准号 / 标题" @keyup.enter="resetQuery" />
      </el-form-item>
      <el-form-item label="识别状态">
        <el-select v-model="query.recognition_status" clearable style="width: 140px">
          <el-option v-for="(label, key) in statusLabels" :key="key" :label="label" :value="key" />
        </el-select>
      </el-form-item>
      <el-form-item label="系统建议">
        <el-select v-model="query.decision" clearable style="width: 140px">
          <el-option v-for="(label, key) in decisionLabels" :key="key" :label="label" :value="key" />
        </el-select>
      </el-form-item>
      <el-form-item><el-button :icon="Search" @click="resetQuery">查询</el-button></el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="items" height="calc(100vh - 430px)">
      <el-table-column prop="created_at" label="上传时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column prop="original_file_name" label="原始文件名" min-width="220" show-overflow-tooltip />
      <el-table-column prop="extracted_standard_no" label="提取标准号" width="150" show-overflow-tooltip />
      <el-table-column prop="extracted_title" label="提取标题" min-width="180" show-overflow-tooltip />
      <el-table-column label="文件大小" width="100">
        <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
      </el-table-column>
      <el-table-column label="识别状态" width="110">
        <template #default="{ row }"><StatusTag :status="statusLabel(row.recognition_status)" /></template>
      </el-table-column>
      <el-table-column label="系统建议" width="110">
        <template #default="{ row }">{{ decisionLabel(row.decision) }}</template>
      </el-table-column>
      <el-table-column prop="confidence_score" label="置信度" width="80" />
      <el-table-column prop="risk_level" label="风险" width="70" />
      <el-table-column label="处理状态" width="100">
        <template #default="{ row }">{{ row.final_action ? '已处理' : '待处理' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button link type="primary" @click="openDetail(row.id)">详情</el-button>
            <el-button
              link
              type="primary"
              :loading="analyzingId === row.id"
              :disabled="!!row.final_action"
              @click="analyzeTask(row.id)"
            >
              识别
            </el-button>
            <el-button link type="danger" :disabled="!!row.linked_version_id" @click="deleteTask(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <CursorPager
      :page="pager.page"
      :total="total"
      :has-more="pager.hasMore"
      @prev="prevCursorPage(pager, loadItems)"
      @next="nextCursorPage(pager, loadItems)"
    />

    <el-drawer v-model="detailVisible" size="62%" title="识别详情">
      <div v-loading="detailLoading">
        <template v-if="activeTask">
          <el-alert
            v-if="duplicateDetected"
            type="warning"
            :closable="false"
            show-icon
            title="已存在完全相同文件，建议忽略，不会自动入库。"
            style="margin-bottom: 12px"
          />
          <el-descriptions :column="2" border>
            <el-descriptions-item label="任务 ID">{{ activeTask.id }}</el-descriptions-item>
            <el-descriptions-item label="文件名">{{ activeTask.original_file_name }}</el-descriptions-item>
            <el-descriptions-item label="提取标准号">{{ activeTask.extracted_standard_no || '-' }}</el-descriptions-item>
            <el-descriptions-item label="提取标题">{{ activeTask.extracted_title || '-' }}</el-descriptions-item>
            <el-descriptions-item label="文件 hash">{{ activeTask.file_hash }}</el-descriptions-item>
            <el-descriptions-item label="文件大小">{{ formatSize(activeTask.file_size) }}</el-descriptions-item>
            <el-descriptions-item label="识别状态">{{ statusLabel(activeTask.recognition_status) }}</el-descriptions-item>
            <el-descriptions-item label="系统建议">{{ decisionLabel(activeTask.decision) }}</el-descriptions-item>
            <el-descriptions-item label="置信度">{{ activeTask.confidence_score ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="风险等级">{{ activeTask.risk_level || '-' }}</el-descriptions-item>
            <el-descriptions-item label="建议原因" :span="2">{{ activeTask.decision_reason || '-' }}</el-descriptions-item>
          </el-descriptions>

          <h3 style="margin: 16px 0 8px">候选匹配</h3>
          <div v-if="!activeTask.final_action" class="row-actions" style="margin-bottom: 8px">
            <el-button
              type="primary"
              plain
              :loading="externalSearching"
              @click="runExternalSearch"
            >
              重新联网复核
            </el-button>
            <span style="color: #909399; font-size: 13px">识别时本地无高置信匹配会自动联网；此按钮可重新切片搜索全部已启用可信源</span>
          </div>
          <el-table
            :data="detail?.candidates || []"
            highlight-current-row
            @current-change="row => (selectedCandidateId = row?.id ?? null)"
          >
            <el-table-column label="候选类型" width="110">
              <template #default="{ row }">{{ candidateTypeLabels[row.candidate_type] || row.candidate_type }}</template>
            </el-table-column>
            <el-table-column label="数据来源" width="100">
              <template #default="{ row }">{{ searchBackendLabel(row.search_backend) }}</template>
            </el-table-column>
            <el-table-column prop="source_name" label="来源名称" width="140" show-overflow-tooltip />
            <el-table-column prop="standard_no" label="标准编号" width="140" show-overflow-tooltip />
            <el-table-column prop="standard_name" label="标准名称" min-width="180" show-overflow-tooltip />
            <el-table-column prop="source_status" label="状态" width="90" />
            <el-table-column prop="match_score" label="匹配分数" width="90" />
            <el-table-column prop="match_reason" label="匹配原因" min-width="180" show-overflow-tooltip />
            <el-table-column label="建议动作" width="110">
              <template #default="{ row }">{{ decisionLabel(row.decision_advice === 'manual_review' ? 'need_review' : row.decision_advice) }}</template>
            </el-table-column>
          </el-table>

          <h3 style="margin: 16px 0 8px">识别日志</h3>
          <el-timeline>
            <el-timeline-item v-for="log in detail?.logs || []" :key="log.id" :timestamp="formatDateTime(log.created_at)">
              {{ stepLabel(log.step_name) }} · {{ log.result }} · {{ log.message }}
            </el-timeline-item>
          </el-timeline>

          <div v-if="!activeTask.final_action" style="margin-top: 16px">
            <el-input v-model="confirmRemark" type="textarea" :rows="2" placeholder="处理备注（可选）" />
            <div class="row-actions" style="margin-top: 12px">
              <el-button @click="confirmAction('ignore')">忽略</el-button>
              <el-button @click="confirmAction('mark_review')">待复核</el-button>
              <el-button @click="confirmAction('link_existing')">关联已有</el-button>
              <el-button @click="confirmAction('new_version')">作为新版本</el-button>
              <el-button type="primary" @click="confirmAction('create_document')">新建入库</el-button>
            </div>
          </div>
        </template>
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.panel {
  padding: 16px;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.toolbar-actions {
  display: flex;
  gap: 8px;
}
.row-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.upload-panel {
  width: 100%;
  margin-bottom: 8px;
}

.upload-panel :deep(.el-upload) {
  width: 100%;
}

.upload-panel :deep(.el-upload-dragger) {
  width: 100%;
  min-height: 180px;
  padding: 36px 20px;
  border: 1px dashed #c0c4cc;
  border-radius: 8px;
  background: #fafafa;
  transition: border-color 0.2s, background-color 0.2s;
}

.upload-panel :deep(.el-upload-dragger:hover) {
  border-color: #409eff;
  background: #f5faff;
}

.upload-panel :deep(.el-icon--upload) {
  font-size: 48px;
  color: #909399;
  margin-bottom: 12px;
}

.upload-panel :deep(.el-upload__text) {
  color: #606266;
  font-size: 14px;
}

.upload-panel :deep(.el-upload__text em) {
  color: #409eff;
  font-style: normal;
}

.upload-panel :deep(.el-upload__tip) {
  margin-top: 8px;
  color: #909399;
}
</style>
