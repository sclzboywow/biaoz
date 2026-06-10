<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api, type CollectionTask, type Page, type UrlSource } from '../../api'
import CursorPager from '../../components/governance/CursorPager.vue'
import {
  applyPageResultWithQuery,
  createCursorPager,
  nextCursorPage,
  pageParams,
  prevCursorPage,
  resetCursorPager,
} from '../../composables/useCursorPager'
import { dateTimeFormatter } from '../../utils/tableFormatters'

const urlSources = ref<UrlSource[]>([])
const collectionTasks = ref<CollectionTask[]>([])
const urlTotal = ref(0)
const checkingAll = ref(false)
const collectionActiveTab = ref('sources')
const collectionTableHeight = 'calc(100vh - 360px)'
const pageSizeOptions = [20, 50, 100, 200]

const urlQuery = reactive({ page: 1, page_size: 50, q: '', status: '', check_frequency: '' })
const urlPager = createCursorPager()

async function loadUrlSources() {
  const res = await api.get<Page<UrlSource>>('/url-sources/page', { params: pageParams(urlQuery, urlPager) })
  urlSources.value = res.data.items
  urlTotal.value = res.data.total
  applyPageResultWithQuery(urlQuery, urlPager, res.data)
}

async function resetUrlSources() {
  resetCursorPager(urlPager)
  await loadUrlSources()
}

async function loadCollectionTasks() {
  const res = await api.get<CollectionTask[]>('/collection-tasks')
  collectionTasks.value = res.data
}

async function createUrlCheckTask() {
  checkingAll.value = true
  try {
    const res = await api.post<CollectionTask>('/collection-tasks/url-check', { include_manual: false, batch_size: 50 })
    ElMessage.success(`已创建后台检查任务 #${res.data.id}`)
    await loadCollectionTasks()
  } finally {
    checkingAll.value = false
  }
}

async function resumeCollectionTask(id: number) {
  await api.post<CollectionTask>(`/collection-tasks/${id}/resume`)
  ElMessage.success(`后台任务 #${id} 已继续执行`)
  await loadCollectionTasks()
}

async function checkSource(id: number) {
  const res = await api.post(`/url-sources/${id}/check`)
  ElMessage.success(res.data.message)
  await Promise.all([loadUrlSources(), loadCollectionTasks()])
}

function taskPercent(row: CollectionTask) {
  if (!row.total) return row.status === 'finished' ? 100 : 0
  return Math.min(100, Math.round((row.processed / row.total) * 100))
}

onMounted(async () => {
  await Promise.all([loadUrlSources(), loadCollectionTasks()])
})
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>文件采集管理</h2>
      <div>
        <el-button :icon="Refresh" @click="loadCollectionTasks">刷新任务</el-button>
        <el-button type="primary" :loading="checkingAll" @click="createUrlCheckTask">创建后台检查任务</el-button>
      </div>
    </div>
    <el-tabs v-model="collectionActiveTab" class="content-tabs">
      <el-tab-pane label="采集来源" name="sources">
        <el-alert title="已导入的大批量 URL 默认是 manual，不会被后台自动下载。需要采集时可在 URL 来源管理中单条检查，或后续按分类/批次放开频率。" type="info" :closable="false" />
        <el-table :data="urlSources" :height="collectionTableHeight" style="margin-top: 14px">
          <el-table-column prop="source_name" label="来源名称" min-width="260" show-overflow-tooltip />
          <el-table-column prop="status" label="链接状态" width="110" />
          <el-table-column prop="error_message" label="异常信息" min-width="260" show-overflow-tooltip />
          <el-table-column prop="last_checked_at" label="最后检查" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
          <el-table-column label="操作" width="120">
            <template #default="{ row }"><el-button size="small" @click="checkSource(row.id)">采集</el-button></template>
          </el-table-column>
        </el-table>
        <CursorPager
          :pager="urlPager"
          :total="urlTotal"
          :page-size-options="pageSizeOptions"
          @prev="prevCursorPage(urlPager, loadUrlSources)"
          @next="nextCursorPage(urlPager, loadUrlSources)"
          @page-size-change="(size) => { urlQuery.page_size = size; resetUrlSources() }"
        />
      </el-tab-pane>
      <el-tab-pane label="后台任务进度" name="tasks">
        <el-table :data="collectionTasks" :height="collectionTableHeight">
          <el-table-column prop="id" label="任务ID" width="90" />
          <el-table-column prop="task_type" label="任务类型" width="120" />
          <el-table-column prop="status" label="状态" width="110" />
          <el-table-column label="进度" width="220">
            <template #default="{ row }">
              <el-progress :percentage="taskPercent(row)" :text-inside="true" :stroke-width="18" />
            </template>
          </el-table-column>
          <el-table-column prop="success" label="成功" width="90" />
          <el-table-column prop="failed" label="失败" width="90" />
          <el-table-column prop="last_source_id" label="游标" width="100" />
          <el-table-column prop="heartbeat_at" label="心跳时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
          <el-table-column prop="message" label="说明" min-width="260" show-overflow-tooltip />
          <el-table-column prop="started_at" label="开始时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
          <el-table-column prop="finished_at" label="完成时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button size="small" :disabled="row.status === 'finished' || row.status === 'running'" @click="resumeCollectionTask(row.id)">继续</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>
