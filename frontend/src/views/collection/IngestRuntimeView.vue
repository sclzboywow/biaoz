<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api, type IngestRuntimeSummary, type IngestRuntimeWorker } from '../../api'

const loading = ref(false)
const summary = ref<IngestRuntimeSummary | null>(null)
const selectedWorker = ref<IngestRuntimeWorker | null>(null)
const detailVisible = ref(false)

const tableHeight = 'calc(100vh - 390px)'

const statusText: Record<string, string> = {
  running: '运行中',
  warning: '有告警',
  stale: '疑似卡住',
  stopped: '已停止',
}

const statusType: Record<string, 'success' | 'warning' | 'info' | 'danger'> = {
  running: 'success',
  warning: 'warning',
  stale: 'warning',
  stopped: 'danger',
}

const workers = computed(() => summary.value?.workers || [])
const channels = computed(() => summary.value?.database.channels || [])
const totals = computed(() => summary.value?.database.totals || {})
const runningCount = computed(() => summary.value?.status_counts.running || 0)
const warningCount = computed(() => (summary.value?.status_counts.warning || 0) + (summary.value?.status_counts.stale || 0))
const stoppedCount = computed(() => summary.value?.status_counts.stopped || 0)

async function loadSummary() {
  loading.value = true
  try {
    const res = await api.get<IngestRuntimeSummary>('/ingest-runtime/summary', { params: { interval_minutes: 30 } })
    summary.value = res.data
  } catch (error) {
    const message = error instanceof Error ? error.message : '加载采集运行状态失败'
    ElMessage.error(message)
  } finally {
    loading.value = false
  }
}

function formatDate(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function summaryCount(row: IngestRuntimeWorker, key: string) {
  return formatValue(row.summary?.[key])
}

function openDetail(row: IngestRuntimeWorker) {
  selectedWorker.value = row
  detailVisible.value = true
}

onMounted(loadSummary)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <div>
        <h2>采集运行控制台</h2>
        <div class="subtle">日志目录：{{ summary?.log_root || '-' }}</div>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadSummary">刷新</el-button>
    </div>

    <div class="status-row">
      <div class="metric">
        <span>运行中脚本</span>
        <strong>{{ runningCount }}</strong>
      </div>
      <div class="metric">
        <span>告警/超时</span>
        <strong>{{ warningCount }}</strong>
      </div>
      <div class="metric">
        <span>已停止</span>
        <strong>{{ stoppedCount }}</strong>
      </div>
      <div class="metric">
        <span>近 30 分钟入库</span>
        <strong>{{ totals.recent_versions || 0 }}</strong>
      </div>
    </div>

    <el-tabs>
      <el-tab-pane label="脚本运行状态">
        <el-table v-loading="loading" :data="workers" :height="tableHeight">
          <el-table-column prop="group" label="分组" width="110" />
          <el-table-column prop="name" label="脚本" min-width="190" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="statusType[row.status] || 'info'">{{ statusText[row.status] || row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="status_message" label="说明" min-width="230" show-overflow-tooltip />
          <el-table-column prop="pid" label="PID" width="90" />
          <el-table-column prop="cursor" label="Cursor" width="110" show-overflow-tooltip />
          <el-table-column label="批次" width="210">
            <template #default="{ row }">
              <span>ok={{ summaryCount(row, 'ok') }}</span>
              <span class="inline-gap">err={{ summaryCount(row, 'errors') }}</span>
              <span class="inline-gap">total={{ summaryCount(row, 'total') }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="last_exit" label="退出码" width="90" />
          <el-table-column prop="log_mtime" label="日志更新时间" width="180">
            <template #default="{ row }">{{ formatDate(row.log_mtime) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="openDetail(row)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="渠道入库统计">
        <el-table :data="channels" :height="tableHeight">
          <el-table-column prop="channel" label="渠道" min-width="180" />
          <el-table-column prop="total" label="当前版本" width="140" />
          <el-table-column prop="recent" label="近 30 分钟" width="140" />
          <el-table-column prop="on_baidu" label="已同步网盘" width="140" />
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="detailVisible" size="50%" title="脚本运行详情">
      <template v-if="selectedWorker">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="脚本">{{ selectedWorker.name }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ statusText[selectedWorker.status] || selectedWorker.status }}</el-descriptions-item>
          <el-descriptions-item label="说明">{{ selectedWorker.status_message }}</el-descriptions-item>
          <el-descriptions-item label="PID">{{ selectedWorker.pid || '-' }}</el-descriptions-item>
          <el-descriptions-item label="PID 文件">{{ selectedWorker.pid_file }}</el-descriptions-item>
          <el-descriptions-item label="日志文件">{{ selectedWorker.log_file }}</el-descriptions-item>
          <el-descriptions-item label="最近开始">{{ selectedWorker.last_started || '-' }}</el-descriptions-item>
          <el-descriptions-item label="最近完成">{{ selectedWorker.last_finished || '-' }}</el-descriptions-item>
          <el-descriptions-item label="批次摘要">{{ formatValue(selectedWorker.summary) }}</el-descriptions-item>
          <el-descriptions-item label="上传摘要">{{ formatValue(selectedWorker.upload_summary) }}</el-descriptions-item>
        </el-descriptions>
        <h3 class="section-title">日志尾部</h3>
        <pre class="json-block">{{ selectedWorker.tail.join('\n') }}</pre>
      </template>
    </el-drawer>
  </section>
</template>

<style scoped>
.subtle {
  margin-top: 4px;
  color: #6b7280;
  font-size: 13px;
}

.inline-gap {
  margin-left: 10px;
}
</style>
