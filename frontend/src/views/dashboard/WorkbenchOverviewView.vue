<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { api, type Alert, type DocumentItem, type Page, type UrlSource } from '../../api'
import CursorPager from '../../components/governance/CursorPager.vue'
import {
  applyPageResultWithQuery,
  createCursorPager,
  nextCursorPage,
  pageParams,
  prevCursorPage,
  resetCursorPager,
} from '../../composables/useCursorPager'
import { useObjectNavigation } from '../../composables/useObjectNavigation'

const { openEvidence } = useObjectNavigation()

const urlTotal = ref(0)
const documentTotal = ref(0)
const pendingReviewCount = ref(0)
const pendingAlertCount = ref(0)
const alerts = ref<Alert[]>([])
const alertTotal = ref(0)
const alertQuery = reactive({ page: 1, page_size: 50, q: '', status: '已处理' })
const alertPager = createCursorPager()
const pageSizeOptions = [20, 50, 100, 200]
const dashboardTableHeight = 'calc(100vh - 330px)'

async function loadUrlSources() {
  const res = await api.get<Page<UrlSource>>('/url-sources/page', { params: { page_size: 1 } })
  urlTotal.value = res.data.total
}

async function loadDocumentCount() {
  const res = await api.get<Page<DocumentItem>>('/documents/page', { params: { page_size: 1 } })
  documentTotal.value = res.data.total
}

async function loadAlerts() {
  const res = await api.get<Page<Alert>>('/alerts/page', { params: pageParams(alertQuery, alertPager) })
  alerts.value = res.data.items
  alertTotal.value = res.data.total
  applyPageResultWithQuery(alertQuery, alertPager, res.data)
}

async function loadCounts() {
  const pendingDocs = await api.get<Page<DocumentItem>>('/documents/page', { params: { page: 1, page_size: 1, system_status: '待复核' } })
  const pendingAlerts = await api.get<Page<Alert>>('/alerts/page', { params: { page: 1, page_size: 1, status: '已处理' } })
  pendingReviewCount.value = pendingDocs.data.total
  pendingAlertCount.value = pendingAlerts.data.total
}

async function resetAlerts() {
  resetCursorPager(alertPager)
  await loadAlerts()
}

async function loadAll() {
  await Promise.all([loadUrlSources(), loadDocumentCount(), loadAlerts(), loadCounts()])
}

onMounted(loadAll)
</script>

<template>
  <section>
    <div class="status-row">
      <div class="metric">URL 来源<strong>{{ urlTotal }}</strong></div>
      <div class="metric">文件库<strong>{{ documentTotal }}</strong></div>
      <div class="metric">待复核<strong>{{ pendingReviewCount }}</strong></div>
      <div class="metric">已处理提醒<strong>{{ pendingAlertCount }}</strong></div>
    </div>
    <div class="panel">
      <div class="toolbar">
        <h2>最近提醒</h2>
        <el-button :icon="Refresh" @click="loadAll">刷新</el-button>
      </div>
      <el-table :data="alerts" :height="dashboardTableHeight">
        <el-table-column prop="alert_level" label="等级" width="90" />
        <el-table-column prop="alert_type" label="类型" width="140" />
        <el-table-column prop="message" label="消息" />
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column label="链路" width="110">
          <template #default="{ row }">
            <el-button size="small" :disabled="!row.document_id" @click.stop="openEvidence(undefined, row.document_id)">文件链路</el-button>
          </template>
        </el-table-column>
      </el-table>
      <CursorPager
        :pager="alertPager"
        :total="alertTotal"
        :page-size-options="pageSizeOptions"
        @prev="prevCursorPage(alertPager, loadAlerts)"
        @next="nextCursorPage(alertPager, loadAlerts)"
        @page-size-change="(size) => { alertQuery.page_size = size; resetAlerts() }"
      />
    </div>
  </section>
</template>
