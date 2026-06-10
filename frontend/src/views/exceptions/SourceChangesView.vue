<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { api, type StandardChangeLog, type Page } from '../../api'
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
import {
  changeDocumentFormatter,
  changeEvidenceFormatter,
  changeFieldFormatter,
  changeValueFormatter,
  changeVersionFormatter,
} from '../../utils/changeFormatters'
import { dateTimeFormatter } from '../../utils/tableFormatters'

const { openEvidence, goStandardDetail } = useObjectNavigation()

const sourceChanges = ref<StandardChangeLog[]>([])
const sourceChangeTotal = ref(0)
const plainTableHeight = 'calc(100vh - 170px)'
const pageSizeOptions = [20, 50, 100, 200]
const sourceChangeQuery = reactive({ page: 1, page_size: 50 })
const sourceChangePager = createCursorPager()

async function loadSourceChanges() {
  const res = await api.get<Page<StandardChangeLog>>('/standard-change-logs/page', { params: pageParams(sourceChangeQuery, sourceChangePager) })
  sourceChanges.value = res.data.items
  sourceChangeTotal.value = res.data.total
  applyPageResultWithQuery(sourceChangeQuery, sourceChangePager, res.data)
}

async function resetSourceChanges() {
  resetCursorPager(sourceChangePager)
  await loadSourceChanges()
}

onMounted(loadSourceChanges)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>变更监测</h2>
      <el-button :icon="Refresh" @click="loadSourceChanges">刷新</el-button>
    </div>
    <el-table :data="sourceChanges" :height="plainTableHeight">
      <el-table-column prop="standard_resource_id" label="资源ID" width="110" />
      <el-table-column prop="document_title" label="本地文件" min-width="220" :formatter="changeDocumentFormatter" show-overflow-tooltip />
      <el-table-column prop="version_no" label="版本" min-width="180" :formatter="changeVersionFormatter" show-overflow-tooltip />
      <el-table-column prop="field_name" label="字段" width="150" :formatter="changeFieldFormatter" />
      <el-table-column prop="change_type" label="变化类型" width="130" />
      <el-table-column prop="old_value" label="旧值" min-width="220" :formatter="changeValueFormatter" show-overflow-tooltip />
      <el-table-column prop="new_value" label="新值" min-width="220" :formatter="changeValueFormatter" show-overflow-tooltip />
      <el-table-column prop="handled_status" label="处理状态" width="120" />
      <el-table-column prop="evidence_summary" label="证据链" min-width="280" :formatter="changeEvidenceFormatter" show-overflow-tooltip />
      <el-table-column prop="detected_at" label="发现时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
      <el-table-column label="链路" width="210" fixed="right">
        <template #default="{ row }">
          <el-button size="small" :disabled="!row.document_id" @click.stop="openEvidence(undefined, row.document_id)">文件</el-button>
          <el-button size="small" @click.stop="goStandardDetail(row.standard_resource_id)">资源</el-button>
        </template>
      </el-table-column>
    </el-table>
    <CursorPager
      :pager="sourceChangePager"
      :total="sourceChangeTotal"
      :page-size-options="pageSizeOptions"
      @prev="prevCursorPage(sourceChangePager, loadSourceChanges)"
      @next="nextCursorPage(sourceChangePager, loadSourceChanges)"
      @page-size-change="(size) => { sourceChangeQuery.page_size = size; resetSourceChanges() }"
    />
  </section>
</template>
