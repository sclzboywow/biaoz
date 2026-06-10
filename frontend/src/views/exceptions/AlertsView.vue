<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { api, type Alert, type Page } from '../../api'
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
import { dateTimeFormatter } from '../../utils/tableFormatters'

const { openEvidence } = useObjectNavigation()

const alerts = ref<Alert[]>([])
const alertTotal = ref(0)
const pagedTableHeight = 'calc(100vh - 260px)'
const pageSizeOptions = [20, 50, 100, 200]
const alertQuery = reactive({ page: 1, page_size: 50, q: '', status: '' })
const alertPager = createCursorPager()

async function loadAlerts() {
  const res = await api.get<Page<Alert>>('/alerts/page', { params: pageParams(alertQuery, alertPager) })
  alerts.value = res.data.items
  alertTotal.value = res.data.total
  applyPageResultWithQuery(alertQuery, alertPager, res.data)
}

async function resetAlerts() {
  resetCursorPager(alertPager)
  await loadAlerts()
}

onMounted(loadAlerts)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>异常提醒</h2>
      <el-button :icon="Refresh" @click="loadAlerts">刷新</el-button>
    </div>
    <el-form :inline="true" class="filters">
      <el-form-item label="查询"><el-input v-model="alertQuery.q" clearable placeholder="提醒内容" @keyup.enter="resetAlerts" /></el-form-item>
      <el-form-item label="状态"><el-select v-model="alertQuery.status" clearable style="width: 130px"><el-option label="未处理" value="未处理" /><el-option label="已处理" value="已处理" /><el-option label="忽略" value="忽略" /></el-select></el-form-item>
      <el-form-item><el-button :icon="Search" @click="resetAlerts">查询</el-button></el-form-item>
    </el-form>
    <el-table :data="alerts" :height="pagedTableHeight">
      <el-table-column prop="alert_level" label="等级" width="90" />
      <el-table-column prop="alert_type" label="类型" width="140" />
      <el-table-column prop="message" label="消息" min-width="320" show-overflow-tooltip />
      <el-table-column prop="status" label="状态" width="110" />
      <el-table-column prop="handled_by" label="处理人" width="130" />
      <el-table-column prop="handled_at" label="处理时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
      <el-table-column prop="created_at" label="创建时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
      <el-table-column label="链路" width="110" fixed="right">
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
  </section>
</template>
