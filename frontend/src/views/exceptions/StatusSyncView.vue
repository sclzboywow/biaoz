<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api, type SourceStatusSyncLog, type Page } from '../../api'
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

const { openEvidence, goStandardDetail } = useObjectNavigation()

const statusSyncLogs = ref<SourceStatusSyncLog[]>([])
const statusSyncTotal = ref(0)
const plainTableHeight = 'calc(100vh - 170px)'
const pageSizeOptions = [20, 50, 100, 200]
const statusSyncQuery = reactive({ page: 1, page_size: 50 })
const statusSyncPager = createCursorPager()

async function loadStatusSyncLogs() {
  const res = await api.get<Page<SourceStatusSyncLog>>('/source-status-sync-logs/page', { params: pageParams(statusSyncQuery, statusSyncPager) })
  statusSyncLogs.value = res.data.items
  statusSyncTotal.value = res.data.total
  applyPageResultWithQuery(statusSyncQuery, statusSyncPager, res.data)
}

async function resetStatusSyncLogs() {
  resetCursorPager(statusSyncPager)
  await loadStatusSyncLogs()
}

onMounted(loadStatusSyncLogs)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>状态同步</h2>
      <el-button :icon="Refresh" @click="loadStatusSyncLogs">刷新</el-button>
    </div>
    <el-table :data="statusSyncLogs" :height="plainTableHeight">
      <el-table-column prop="standard_resource_id" label="可信源资源" width="130" />
      <el-table-column prop="document_id" label="本地文件" width="110" />
      <el-table-column prop="old_status" label="原状态" width="140" />
      <el-table-column prop="new_status" label="新状态" width="140" />
      <el-table-column prop="sync_action" label="动作" width="150" />
      <el-table-column prop="sync_reason" label="原因/证据" min-width="360" show-overflow-tooltip />
      <el-table-column prop="synced_at" label="同步时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
      <el-table-column label="链路" width="210" fixed="right">
        <template #default="{ row }">
          <el-button size="small" :disabled="!row.document_id" @click.stop="openEvidence(undefined, row.document_id)">文件</el-button>
          <el-button size="small" @click.stop="goStandardDetail(row.standard_resource_id)">资源</el-button>
        </template>
      </el-table-column>
    </el-table>
    <CursorPager
      :pager="statusSyncPager"
      :total="statusSyncTotal"
      :page-size-options="pageSizeOptions"
      @prev="prevCursorPage(statusSyncPager, loadStatusSyncLogs)"
      @next="nextCursorPage(statusSyncPager, loadStatusSyncLogs)"
      @page-size-change="(size) => { statusSyncQuery.page_size = size; resetStatusSyncLogs() }"
    />
  </section>
</template>
