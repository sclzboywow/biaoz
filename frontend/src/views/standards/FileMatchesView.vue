<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Aim } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api, type StandardFileMatch, type Page } from '../../api'
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

const fileMatches = ref<StandardFileMatch[]>([])
const fileMatchTotal = ref(0)
const plainTableHeight = 'calc(100vh - 170px)'
const pageSizeOptions = [20, 50, 100, 200]
const fileMatchQuery = reactive({ page: 1, page_size: 50 })
const fileMatchPager = createCursorPager()

async function loadFileMatches() {
  const res = await api.get<Page<StandardFileMatch>>('/standard-file-matches/page', { params: pageParams(fileMatchQuery, fileMatchPager) })
  fileMatches.value = res.data.items
  fileMatchTotal.value = res.data.total
  applyPageResultWithQuery(fileMatchQuery, fileMatchPager, res.data)
}

async function resetFileMatches() {
  resetCursorPager(fileMatchPager)
  await loadFileMatches()
}

async function runFileMatch() {
  const res = await api.post('/standard-file-matches/run')
  ElMessage.success(`匹配 ${res.data.matched} 条，跳过 ${res.data.skipped} 条`)
  await loadFileMatches()
}

onMounted(loadFileMatches)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>本地文件匹配</h2>
      <el-button type="primary" :icon="Aim" @click="runFileMatch">按编号自动匹配</el-button>
    </div>
    <el-table :data="fileMatches" :height="plainTableHeight">
      <el-table-column prop="standard_resource_id" label="可信源资源" width="130" />
      <el-table-column prop="document_id" label="本地文件" width="110" />
      <el-table-column prop="match_type" label="匹配方式" width="160" />
      <el-table-column prop="match_score" label="分数" width="90" />
      <el-table-column prop="match_reason" label="原因" min-width="260" />
      <el-table-column prop="status" label="状态" width="120" />
      <el-table-column prop="matched_at" label="匹配时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
      <el-table-column label="链路" width="210" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click.stop="openEvidence(undefined, row.document_id)">文件</el-button>
          <el-button size="small" @click.stop="goStandardDetail(row.standard_resource_id)">资源</el-button>
        </template>
      </el-table-column>
    </el-table>
    <CursorPager
      :pager="fileMatchPager"
      :total="fileMatchTotal"
      :page-size-options="pageSizeOptions"
      @prev="prevCursorPage(fileMatchPager, loadFileMatches)"
      @next="nextCursorPage(fileMatchPager, loadFileMatches)"
      @page-size-change="(size) => { fileMatchQuery.page_size = size; resetFileMatches() }"
    />
  </section>
</template>
