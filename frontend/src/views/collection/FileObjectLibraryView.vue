<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { api, type FileObjectItem, type FileObjectPage, type FileObjectsSummary } from '../../api'
import CursorPager from '../../components/governance/CursorPager.vue'
import MetricCard from '../../components/governance/MetricCard.vue'
import { applyPageResult, createCursorPager, nextCursorPage, prevCursorPage, resetCursorPager } from '../../composables/useCursorPager'
import { useObjectNavigation } from '../../composables/useObjectNavigation'
import { formatDateTime, formatFileSize } from '../../utils/formatters'

const { openFileObject } = useObjectNavigation()

const summary = ref<FileObjectsSummary | null>(null)
const items = ref<FileObjectItem[]>([])
const total = ref(0)
const loading = ref(false)
const pager = createCursorPager()
const query = reactive({
  q: '',
  pdf_valid: undefined as boolean | undefined,
  filter_type: '',
})

async function loadSummary() {
  const res = await api.get<FileObjectsSummary>('/file-objects/summary')
  summary.value = res.data
}

async function loadItems() {
  loading.value = true
  try {
    const res = await api.get<FileObjectPage>('/file-objects/page', {
      params: {
        cursor: pager.cursors[pager.page - 1] ?? undefined,
        page_size: 50,
        q: query.q || undefined,
        pdf_valid: query.pdf_valid,
        filter_type: query.filter_type || undefined,
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

function onRowClick(row: FileObjectItem) {
  openFileObject(row.id)
}

onMounted(async () => {
  await Promise.all([loadSummary(), loadItems()])
})
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>文件对象库</h2>
      <el-button :icon="Refresh" @click="loadSummary(); loadItems()">刷新</el-button>
    </div>
    <div v-if="summary" class="status-row">
      <MetricCard label="总数" :value="summary.total" />
      <MetricCard label="PDF 有效" :value="summary.pdf_valid" highlight="success" />
      <MetricCard label="PDF 无效" :value="summary.pdf_invalid" highlight="danger" />
      <MetricCard label="无关联标准" :value="summary.unlinked" highlight="warning" />
    </div>
    <el-form :inline="true" class="filters" style="margin-top: 12px">
      <el-form-item label="查询"><el-input v-model="query.q" clearable @keyup.enter="resetQuery" /></el-form-item>
      <el-form-item label="PDF"><el-select v-model="query.pdf_valid" clearable style="width: 120px"><el-option label="有效" :value="true" /><el-option label="无效" :value="false" /></el-select></el-form-item>
      <el-form-item label="筛选"><el-select v-model="query.filter_type" clearable style="width: 160px"><el-option label="大文件" value="large" /><el-option label="无关联标准" value="unlinked" /></el-select></el-form-item>
      <el-form-item><el-button :icon="Search" @click="resetQuery">查询</el-button></el-form-item>
    </el-form>
    <el-table v-loading="loading" :data="items" height="calc(100vh - 340px)" @row-click="onRowClick">
      <el-table-column prop="file_hash" label="file_hash" min-width="260" show-overflow-tooltip />
      <el-table-column label="文件大小" width="110"><template #default="{ row }">{{ formatFileSize(row.file_size) }}</template></el-table-column>
      <el-table-column prop="pdf_validation_status" label="PDF 状态" width="120" />
      <el-table-column prop="local_path" label="存储位置" min-width="220" show-overflow-tooltip />
      <el-table-column prop="linked_standard_count" label="关联标准" width="100" />
      <el-table-column prop="created_at" label="创建时间" width="170"><template #default="{ row }">{{ formatDateTime(row.created_at) }}</template></el-table-column>
    </el-table>
    <CursorPager :pager="pager" :total="total" @prev="prevCursorPage(pager, loadItems)" @next="nextCursorPage(pager, loadItems)" />
  </section>
</template>
