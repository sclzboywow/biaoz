<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api, type UrlSource } from '../../api'
import AuditLogDrawer from '../../components/governance/AuditLogDrawer.vue'
import CursorPager from '../../components/governance/CursorPager.vue'
import StatusTag from '../../components/governance/StatusTag.vue'
import { applyPageResult, createCursorPager, nextCursorPage, prevCursorPage, resetCursorPager } from '../../composables/useCursorPager'
import { useGlobalDialogs } from '../../composables/useGlobalDialogs'
import { useObjectNavigation } from '../../composables/useObjectNavigation'

const props = withDefaults(
  defineProps<{
    governanceStatusPreset?: string
    title?: string
  }>(),
  {
    governanceStatusPreset: '',
    title: 'URL 来源治理',
  },
)

const { goStandardDetail } = useObjectNavigation()
const { openUrlCreate } = useGlobalDialogs()

const items = ref<UrlSource[]>([])
const total = ref(0)
const loading = ref(false)
const selectedIds = ref<number[]>([])
const pager = createCursorPager()
const auditVisible = ref(false)
const auditTargetId = ref<number>()
const query = reactive({
  q: '',
  status: '',
  check_frequency: '',
  host: '',
  url_type: '',
  governance_status: props.governanceStatusPreset,
  score_min: undefined as number | undefined,
  score_max: undefined as number | undefined,
  is_official_domain: undefined as boolean | undefined,
  is_cloud_drive: undefined as boolean | undefined,
  is_probable_pdf: undefined as boolean | undefined,
  need_ocr: undefined as boolean | undefined,
  is_duplicate: undefined as boolean | undefined,
  page_size: 50,
})

async function loadItems() {
  loading.value = true
  try {
    const res = await api.get<{ total: number; items: UrlSource[]; next_cursor?: number | null; has_more: boolean }>('/url-sources/page', {
      params: {
        cursor: pager.cursors[pager.page - 1] ?? undefined,
        page_size: query.page_size,
        q: query.q || undefined,
        status: query.status || undefined,
        check_frequency: query.check_frequency || undefined,
        host: query.host || undefined,
        url_type: query.url_type || undefined,
        governance_status: query.governance_status || undefined,
        score_min: query.score_min,
        score_max: query.score_max,
        is_official_domain: query.is_official_domain,
        is_cloud_drive: query.is_cloud_drive,
        is_probable_pdf: query.is_probable_pdf,
        need_ocr: query.need_ocr,
        is_duplicate: query.is_duplicate,
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

async function runAction(id: number, action: string) {
  await api.post(`/url-sources/${id}/governance-action`, { action })
  ElMessage.success('操作成功')
  await loadItems()
}

async function runBatch(action: string) {
  if (!selectedIds.value.length) {
    ElMessage.warning('请先选择 URL')
    return
  }
  await api.post('/url-sources/governance/batch-action', { source_ids: selectedIds.value, action })
  ElMessage.success('批量操作成功')
  selectedIds.value = []
  await loadItems()
}

function openAudit(id: number) {
  auditTargetId.value = id
  auditVisible.value = true
}

function onRowClick(row: UrlSource & { standard_resource_id?: number | null }) {
  if (row.standard_resource_id) {
    goStandardDetail(row.standard_resource_id)
  }
}

onMounted(loadItems)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>{{ title }}</h2>
      <div class="toolbar-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadItems">刷新</el-button>
        <el-button @click="runBatch('reprofile')">批量重新画像</el-button>
        <el-button @click="runBatch('mark_clue')">批量降级为线索</el-button>
        <el-button @click="runBatch('pause_collect')">批量暂停采集</el-button>
        <el-button @click="runBatch('to_ocr_queue')">批量转 OCR</el-button>
        <el-button type="primary" :icon="Plus" @click="openUrlCreate">新增</el-button>
      </div>
    </div>
    <el-form :inline="true" class="filters">
      <el-form-item label="查询"><el-input v-model="query.q" clearable @keyup.enter="resetQuery" /></el-form-item>
      <el-form-item label="host"><el-input v-model="query.host" clearable style="width: 140px" /></el-form-item>
      <el-form-item label="治理状态"><el-input v-model="query.governance_status" clearable style="width: 120px" /></el-form-item>
      <el-form-item><el-button :icon="Search" @click="resetQuery">查询</el-button></el-form-item>
    </el-form>
    <el-table v-loading="loading" :data="items" height="calc(100vh - 340px)" @selection-change="rows => (selectedIds = rows.map(r => r.id))" @row-click="onRowClick">
      <el-table-column type="selection" width="48" />
      <el-table-column prop="source_name" label="来源名称" min-width="160" show-overflow-tooltip />
      <el-table-column prop="host" label="host" width="140" show-overflow-tooltip />
      <el-table-column prop="url_type" label="url_type" width="120" />
      <el-table-column prop="source_quality_score" label="质量分" width="80" />
      <el-table-column label="治理状态" width="120"><template #default="{ row }"><StatusTag :status="row.governance_status" /></template></el-table-column>
      <el-table-column label="操作" width="560" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button size="small" @click.stop="runAction(row.id, 'reprofile')">重新画像</el-button>
            <el-button size="small" @click.stop="runAction(row.id, 'mark_clue')">只作线索</el-button>
            <el-button size="small" @click.stop="runAction(row.id, 'blacklist_candidate')">黑名单候选</el-button>
            <el-button size="small" @click.stop="runAction(row.id, 'to_ocr_queue')">转 OCR</el-button>
            <el-button size="small" @click.stop="openAudit(row.id)">审计日志</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
    <CursorPager :pager="pager" :total="total" @prev="prevCursorPage(pager, loadItems)" @next="nextCursorPage(pager, loadItems)" />
    <AuditLogDrawer v-model:visible="auditVisible" target-type="url_source" :target-id="auditTargetId" process-type="source_governance" />
  </section>
</template>
