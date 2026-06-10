<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { api, type DocumentVersion, type Page } from '../../api'
import CursorPager from '../../components/governance/CursorPager.vue'
import {
  applyPageResultWithQuery,
  createCursorPager,
  nextCursorPage,
  pageParams,
  prevCursorPage,
  resetCursorPager,
} from '../../composables/useCursorPager'
import { dateTimeFormatter, fileSizeMbFormatter } from '../../utils/tableFormatters'

const versions = ref<DocumentVersion[]>([])
const versionTotal = ref(0)
const pagedTableHeight = 'calc(100vh - 260px)'
const pageSizeOptions = [20, 50, 100, 200]
const versionQuery = reactive({ page: 1, page_size: 50 })
const versionPager = createCursorPager()

function versionFileUrl(versionId: number, inline: boolean) {
  const baseUrl = String(api.defaults.baseURL || '').replace(/\/$/, '')
  return `${baseUrl}/document-versions/${versionId}/file?inline=${inline ? 'true' : 'false'}`
}

function openVersionFile(version: DocumentVersion, inline: boolean) {
  window.open(versionFileUrl(version.id, inline), '_blank', 'noopener')
}

async function loadVersions() {
  const res = await api.get<Page<DocumentVersion>>('/document-versions/page', { params: pageParams(versionQuery, versionPager) })
  versions.value = res.data.items
  versionTotal.value = res.data.total
  applyPageResultWithQuery(versionQuery, versionPager, res.data)
}

async function resetVersions() {
  resetCursorPager(versionPager)
  await loadVersions()
}

onMounted(loadVersions)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>版本管理</h2>
      <el-button :icon="Refresh" @click="resetVersions">刷新</el-button>
    </div>
    <el-table :data="versions" :height="pagedTableHeight">
      <el-table-column prop="document_id" label="文件ID" width="90" />
      <el-table-column prop="standard_no" label="标准编号" width="150" show-overflow-tooltip />
      <el-table-column prop="version_no" label="版本" width="90" />
      <el-table-column prop="document_title" label="文件标题" min-width="320" show-overflow-tooltip />
      <el-table-column prop="file_name" label="归档文件名" min-width="220" show-overflow-tooltip />
      <el-table-column prop="change_type" label="变化" width="100" />
      <el-table-column prop="is_current" label="当前" width="90" />
      <el-table-column prop="file_size" label="大小(MB)" width="110" :formatter="fileSizeMbFormatter" />
      <el-table-column prop="file_hash" label="SHA-256" min-width="240" show-overflow-tooltip />
      <el-table-column prop="downloaded_at" label="下载时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
      <el-table-column label="文件" width="150" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openVersionFile(row, true)">预览</el-button>
          <el-button size="small" @click="openVersionFile(row, false)">下载</el-button>
        </template>
      </el-table-column>
    </el-table>
    <CursorPager
      :pager="versionPager"
      :total="versionTotal"
      :page-size-options="pageSizeOptions"
      @prev="prevCursorPage(versionPager, loadVersions)"
      @next="nextCursorPage(versionPager, loadVersions)"
      @page-size-change="(size) => { versionQuery.page_size = size; resetVersions() }"
    />
  </section>
</template>
