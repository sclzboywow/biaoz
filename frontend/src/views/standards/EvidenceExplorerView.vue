<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Link, Refresh, Search, View as ViewIcon } from '@element-plus/icons-vue'
import { api, type Page, type StandardEvidence } from '../../api'
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

const { goStandardDetail, openEvidence } = useObjectNavigation()

const items = ref<StandardEvidence[]>([])
const total = ref(0)
const loading = ref(false)
const detailVisible = ref(false)
const selectedEvidence = ref<StandardEvidence | null>(null)
const pageSizeOptions = [20, 50, 100, 200]
const pager = createCursorPager()
const query = reactive({
  page: 1,
  page_size: 50,
  q: '',
  source_name: '',
  source_level: '',
  raw_status_text: '',
  parsed_status: '',
})

const summaryText = computed(() => selectedEvidence.value?.page_summary || selectedEvidence.value?.evidence_note || '')

async function loadItems() {
  loading.value = true
  try {
    const res = await api.get<Page<StandardEvidence>>('/standard-evidence/page', {
      params: pageParams(query, pager),
    })
    items.value = res.data.items
    total.value = res.data.total
    applyPageResultWithQuery(query, pager, res.data)
  } finally {
    loading.value = false
  }
}

async function resetQuery() {
  resetCursorPager(pager)
  await loadItems()
}

function openDetail(row: StandardEvidence) {
  selectedEvidence.value = row
  detailVisible.value = true
}

function openExternal(url?: string | null) {
  if (!url) return
  window.open(url, '_blank', 'noopener,noreferrer')
}

function openStandard(row: StandardEvidence) {
  if (row.standard_resource_id) {
    goStandardDetail(row.standard_resource_id)
  }
}

function openChain(row: StandardEvidence) {
  openEvidence(row.standard_resource_id, row.document_id)
}

onMounted(loadItems)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>证据链</h2>
      <el-button :icon="Refresh" :loading="loading" @click="loadItems">刷新</el-button>
    </div>

    <el-form :inline="true" class="filters">
      <el-form-item label="查询">
        <el-input v-model="query.q" clearable placeholder="标准号、名称、文件、来源、状态、说明、URL" style="width: 360px" @keyup.enter="resetQuery" />
      </el-form-item>
      <el-form-item label="来源">
        <el-input v-model="query.source_name" clearable style="width: 180px" @keyup.enter="resetQuery" />
      </el-form-item>
      <el-form-item label="等级">
        <el-select v-model="query.source_level" clearable style="width: 110px">
          <el-option label="A" value="A" />
          <el-option label="B" value="B" />
          <el-option label="C" value="C" />
        </el-select>
      </el-form-item>
      <el-form-item label="原始状态">
        <el-input v-model="query.raw_status_text" clearable style="width: 120px" @keyup.enter="resetQuery" />
      </el-form-item>
      <el-form-item label="解析状态">
        <el-input v-model="query.parsed_status" clearable style="width: 120px" @keyup.enter="resetQuery" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :icon="Search" :loading="loading" @click="resetQuery">查询</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="items" height="calc(100vh - 340px)" @row-dblclick="openDetail">
      <el-table-column prop="standard_no" label="标准号" width="170" show-overflow-tooltip />
      <el-table-column prop="standard_name" label="标准名称" min-width="280" show-overflow-tooltip />
      <el-table-column prop="document_title" label="本地文件" min-width="220" show-overflow-tooltip />
      <el-table-column prop="source_name" label="来源" width="170" show-overflow-tooltip />
      <el-table-column prop="source_level" label="等级" width="70" />
      <el-table-column prop="raw_status_text" label="原始状态" width="110" show-overflow-tooltip />
      <el-table-column prop="parsed_status" label="解析状态" width="110" show-overflow-tooltip />
      <el-table-column prop="evidence_note" label="证据说明" min-width="280" show-overflow-tooltip />
      <el-table-column prop="captured_at" label="抓取时间" width="170" :formatter="dateTimeFormatter" />
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button size="small" :icon="ViewIcon" @click.stop="openDetail(row)">详情</el-button>
            <el-button size="small" :disabled="!row.standard_resource_id" @click.stop="openStandard(row)">标准</el-button>
            <el-button size="small" @click.stop="openChain(row)">链路</el-button>
            <el-button size="small" :icon="Link" :disabled="!row.source_url" @click.stop="openExternal(row.source_url)">来源</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <CursorPager
      :pager="pager"
      :total="total"
      :page-size-options="pageSizeOptions"
      @prev="prevCursorPage(pager, loadItems)"
      @next="nextCursorPage(pager, loadItems)"
      @page-size-change="(size) => { query.page_size = size; resetQuery() }"
    />
  </section>

  <el-drawer v-model="detailVisible" title="证据详情" size="720px">
    <div v-if="selectedEvidence" class="evidence-detail">
      <dl class="detail-grid">
        <dt>标准号</dt>
        <dd>{{ selectedEvidence.standard_no || '-' }}</dd>
        <dt>标准名称</dt>
        <dd>{{ selectedEvidence.standard_name || '-' }}</dd>
        <dt>本地文件</dt>
        <dd>{{ selectedEvidence.document_title || '-' }}</dd>
        <dt>来源</dt>
        <dd>{{ selectedEvidence.source_name || '-' }}</dd>
        <dt>来源等级</dt>
        <dd>{{ selectedEvidence.source_level || '-' }}</dd>
        <dt>原始状态</dt>
        <dd>{{ selectedEvidence.raw_status_text || '-' }}</dd>
        <dt>解析状态</dt>
        <dd>{{ selectedEvidence.parsed_status || '-' }}</dd>
        <dt>抓取时间</dt>
        <dd>{{ selectedEvidence.captured_at || '-' }}</dd>
        <dt>HTML Hash</dt>
        <dd>{{ selectedEvidence.page_html_hash || '-' }}</dd>
      </dl>
      <div class="detail-links">
        <el-button :icon="Link" :disabled="!selectedEvidence.source_url" @click="openExternal(selectedEvidence.source_url)">来源页面</el-button>
        <el-button :disabled="!selectedEvidence.standard_resource_id" @click="openStandard(selectedEvidence)">标准详情</el-button>
        <el-button @click="openChain(selectedEvidence)">完整链路</el-button>
      </div>
      <h3>说明</h3>
      <pre class="detail-text">{{ summaryText || '-' }}</pre>
    </div>
  </el-drawer>
</template>

<style scoped>
.evidence-detail {
  display: grid;
  gap: 16px;
}

.detail-grid {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 10px 14px;
  margin: 0;
}

.detail-grid dt {
  color: #606266;
}

.detail-grid dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
}

.detail-links {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.evidence-detail h3 {
  margin: 4px 0 0;
  font-size: 15px;
}

.detail-text {
  max-height: 42vh;
  margin: 0;
  padding: 12px;
  overflow: auto;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  background: #f7f8fa;
  color: #303133;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
