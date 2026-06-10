<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { api, type OcrDownloadTask, type OcrDownloadTaskPage, type OcrTasksSummary } from '../../api'
import AuditLogDrawer from '../../components/governance/AuditLogDrawer.vue'
import CursorPager from '../../components/governance/CursorPager.vue'
import MetricCard from '../../components/governance/MetricCard.vue'
import StatusTag from '../../components/governance/StatusTag.vue'
import { applyPageResult, createCursorPager, nextCursorPage, prevCursorPage, resetCursorPager } from '../../composables/useCursorPager'
import { useObjectNavigation } from '../../composables/useObjectNavigation'
import { formatDateTime } from '../../utils/formatters'

type OcrTaskWithFile = OcrDownloadTask & { file_object_id?: number | null }

const { openFileObject } = useObjectNavigation()

const summary = ref<OcrTasksSummary | null>(null)
const items = ref<OcrTaskWithFile[]>([])
const total = ref(0)
const loading = ref(false)
const creating = ref(false)
const createLimit = ref(100)
const selectedIds = ref<number[]>([])
const pager = createCursorPager()
const query = reactive({ status: '', q: '' })
const auditVisible = ref(false)
const auditTargetId = ref<number>()

async function loadSummary() {
  const res = await api.get<OcrTasksSummary>('/ocr-tasks/summary')
  summary.value = res.data
}

async function loadItems() {
  loading.value = true
  try {
    const res = await api.get<OcrDownloadTaskPage>('/ocr-tasks/page', {
      params: {
        cursor: pager.cursors[pager.page - 1] ?? undefined,
        page_size: 50,
        status: query.status || undefined,
        q: query.q || undefined,
      },
    })
    items.value = res.data.items as OcrTaskWithFile[]
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

async function createTasks(dryRun: boolean) {
  creating.value = true
  try {
    const res = await api.post('/ocr-tasks/create-from-decisions', { limit: createLimit.value, only_unprocessed: true, dry_run: dryRun })
    if (!dryRun) {
      await loadSummary()
      await loadItems()
    }
  } finally {
    creating.value = false
  }
}

async function taskAction(id: number, action: 'retry' | 'skip' | 'manual') {
  if (action === 'retry') await api.post(`/ocr-tasks/${id}/retry`)
  if (action === 'skip') await api.post(`/ocr-tasks/${id}/skip`)
  if (action === 'manual') await api.post(`/ocr-tasks/${id}/mark-need-manual`)
  await loadItems()
}

function openAudit(id: number) {
  auditTargetId.value = id
  auditVisible.value = true
}

onMounted(async () => {
  await Promise.all([loadSummary(), loadItems()])
})
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>OCR 下载队列</h2>
      <div class="toolbar-actions">
        <el-input-number v-model="createLimit" :min="10" :max="1000" :step="50" />
        <el-button :icon="Refresh" @click="loadSummary(); loadItems()">刷新</el-button>
        <el-button :loading="creating" @click="createTasks(true)">试跑建任务</el-button>
        <el-button type="primary" :loading="creating" @click="createTasks(false)">从决策建任务</el-button>
      </div>
    </div>
    <div v-if="summary" class="status-row">
      <MetricCard label="待 OCR" :value="summary.pending_ocr" highlight="warning" />
      <MetricCard label="运行中" :value="summary.running" />
      <MetricCard label="已归档" :value="summary.archived" highlight="success" />
      <MetricCard label="OCR 失败" :value="summary.ocr_failed" highlight="danger" />
      <MetricCard label="需人工" :value="summary.need_manual" highlight="warning" />
    </div>
    <el-form :inline="true" class="filters" style="margin-top: 12px">
      <el-form-item label="状态"><el-select v-model="query.status" clearable style="width: 160px"><el-option v-for="s in ['PENDING','RUNNING','ARCHIVED','NEED_MANUAL']" :key="s" :label="s" :value="s" /></el-select></el-form-item>
      <el-form-item label="查询"><el-input v-model="query.q" clearable @keyup.enter="resetQuery" /></el-form-item>
      <el-form-item><el-button :icon="Search" @click="resetQuery">查询</el-button></el-form-item>
    </el-form>
    <el-table v-loading="loading" :data="items" height="calc(100vh - 380px)" @selection-change="rows => (selectedIds = rows.map(r => r.id))">
      <el-table-column prop="standard_no" label="标准编号" width="140" show-overflow-tooltip />
      <el-table-column prop="standard_name" label="标准名称" min-width="220" show-overflow-tooltip />
      <el-table-column label="任务状态" width="130"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
      <el-table-column prop="attempt_count" label="尝试次数" width="90" />
      <el-table-column prop="last_error" label="最后错误" min-width="220" show-overflow-tooltip />
      <el-table-column prop="created_at" label="创建时间" width="170"><template #default="{ row }">{{ formatDateTime(row.created_at) }}</template></el-table-column>
      <el-table-column label="操作" width="420" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button size="small" @click="taskAction(row.id, 'retry')">重试</el-button>
            <el-button size="small" @click="taskAction(row.id, 'skip')">跳过</el-button>
            <el-button size="small" @click="openAudit(row.id)">日志</el-button>
            <el-button v-if="row.status === 'ARCHIVED' && row.file_object_id" size="small" type="primary" @click="openFileObject(row.file_object_id!)">文件对象</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
    <CursorPager :pager="pager" :total="total" @prev="prevCursorPage(pager, loadItems)" @next="nextCursorPage(pager, loadItems)" />
    <AuditLogDrawer v-model:visible="auditVisible" target-type="ocr_download_task" :target-id="auditTargetId" process-type="OCR_DOWNLOAD" />
  </section>
</template>
