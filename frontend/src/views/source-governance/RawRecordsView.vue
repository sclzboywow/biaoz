<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Link, Refresh, Search, View as ViewIcon } from '@element-plus/icons-vue'
import { api, type Page, type RawRecord } from '../../api'
import CursorPager from '../../components/governance/CursorPager.vue'
import StatusTag from '../../components/governance/StatusTag.vue'
import {
  applyPageResultWithQuery,
  createCursorPager,
  nextCursorPage,
  pageParams,
  prevCursorPage,
  resetCursorPager,
} from '../../composables/useCursorPager'
import { dateTimeFormatter } from '../../utils/tableFormatters'

const records = ref<RawRecord[]>([])
const total = ref(0)
const loading = ref(false)
const detailVisible = ref(false)
const selectedRecord = ref<RawRecord | null>(null)
const pageSizeOptions = [20, 50, 100, 200]
const pager = createCursorPager()
const query = reactive({
  page: 1,
  page_size: 50,
  q: '',
  source_sheet: '',
  impl_status: '',
  governance_status: '',
  has_link: undefined as boolean | undefined,
})

const parsedFields = computed(() => {
  const raw = selectedRecord.value?.fields_json
  if (!raw) return ''
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
})

async function loadRecords() {
  loading.value = true
  try {
    const res = await api.get<Page<RawRecord>>('/source-governance/raw-records/page', {
      params: pageParams(query, pager),
    })
    records.value = res.data.items
    total.value = res.data.total
    applyPageResultWithQuery(query, pager, res.data)
  } finally {
    loading.value = false
  }
}

async function resetQuery() {
  resetCursorPager(pager)
  await loadRecords()
}

function openDetail(row: RawRecord) {
  selectedRecord.value = row
  detailVisible.value = true
}

function openExternal(url?: string | null) {
  if (!url) return
  window.open(url, '_blank', 'noopener,noreferrer')
}

onMounted(loadRecords)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>原始记录池</h2>
      <el-button :icon="Refresh" :loading="loading" @click="loadRecords">刷新</el-button>
    </div>

    <el-form :inline="true" class="filters">
      <el-form-item label="查询">
        <el-input v-model="query.q" clearable placeholder="记录 ID、标准号、名称、链接、原始字段" style="width: 360px" @keyup.enter="resetQuery" />
      </el-form-item>
      <el-form-item label="来源">
        <el-select v-model="query.source_sheet" clearable style="width: 150px">
          <el-option label="标准查询系统" value="标准查询系统" />
        </el-select>
      </el-form-item>
      <el-form-item label="实施状态">
        <el-select v-model="query.impl_status" clearable style="width: 130px">
          <el-option label="现行" value="现行" />
          <el-option label="即将实施" value="即将实施" />
          <el-option label="废止" value="废止" />
        </el-select>
      </el-form-item>
      <el-form-item label="治理状态">
        <el-select v-model="query.governance_status" clearable style="width: 130px">
          <el-option label="pending" value="pending" />
          <el-option label="ingested" value="ingested" />
        </el-select>
      </el-form-item>
      <el-form-item label="链接">
        <el-select v-model="query.has_link" clearable style="width: 120px">
          <el-option label="有" :value="true" />
          <el-option label="无" :value="false" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :icon="Search" :loading="loading" @click="resetQuery">查询</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="records" height="calc(100vh - 340px)" @row-dblclick="openDetail">
      <el-table-column prop="serial_no" label="序号" width="90" />
      <el-table-column prop="file_no" label="标准号" width="170" show-overflow-tooltip />
      <el-table-column prop="file_name" label="名称" min-width="300" show-overflow-tooltip />
      <el-table-column prop="impl_status" label="实施状态" width="110" />
      <el-table-column prop="source_sheet" label="来源" width="140" show-overflow-tooltip />
      <el-table-column label="治理状态" width="120">
        <template #default="{ row }">
          <StatusTag :status="row.governance_status" />
        </template>
      </el-table-column>
      <el-table-column prop="wps_fetched_at" label="抓取时间" width="170" :formatter="dateTimeFormatter" />
      <el-table-column prop="wps_record_id" label="记录 ID" width="150" show-overflow-tooltip />
      <el-table-column label="链接" width="120">
        <template #default="{ row }">
          <div class="row-actions compact-actions">
            <el-button :icon="Link" size="small" circle :disabled="!row.link_url" title="打开文件链接" @click.stop="openExternal(row.link_url)" />
            <el-button :icon="Link" size="small" circle :disabled="!row.goto_url" title="打开跳转链接" @click.stop="openExternal(row.goto_url)" />
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="110" fixed="right">
        <template #default="{ row }">
          <el-button size="small" :icon="ViewIcon" @click.stop="openDetail(row)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <CursorPager
      :pager="pager"
      :total="total"
      :page-size-options="pageSizeOptions"
      @prev="prevCursorPage(pager, loadRecords)"
      @next="nextCursorPage(pager, loadRecords)"
      @page-size-change="(size) => { query.page_size = size; resetQuery() }"
    />
  </section>

  <el-drawer v-model="detailVisible" title="原始记录详情" size="720px">
    <div v-if="selectedRecord" class="raw-detail">
      <dl class="detail-grid">
        <dt>记录 ID</dt>
        <dd>{{ selectedRecord.wps_record_id }}</dd>
        <dt>序号</dt>
        <dd>{{ selectedRecord.serial_no || '-' }}</dd>
        <dt>标准号</dt>
        <dd>{{ selectedRecord.file_no || '-' }}</dd>
        <dt>名称</dt>
        <dd>{{ selectedRecord.file_name || '-' }}</dd>
        <dt>实施状态</dt>
        <dd>{{ selectedRecord.impl_status || '-' }}</dd>
        <dt>治理状态</dt>
        <dd>{{ selectedRecord.governance_status }}</dd>
        <dt>来源</dt>
        <dd>{{ selectedRecord.source_sheet }}</dd>
        <dt>抓取时间</dt>
        <dd>{{ selectedRecord.wps_fetched_at || '-' }}</dd>
      </dl>
      <div class="detail-links">
        <el-button :icon="Link" :disabled="!selectedRecord.link_url" @click="openExternal(selectedRecord.link_url)">文件链接</el-button>
        <el-button :icon="Link" :disabled="!selectedRecord.goto_url" @click="openExternal(selectedRecord.goto_url)">跳转链接</el-button>
      </div>
      <h3>原始字段</h3>
      <pre class="raw-json">{{ parsedFields }}</pre>
    </div>
  </el-drawer>
</template>

<style scoped>
.compact-actions {
  gap: 6px;
}

.raw-detail {
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

.raw-detail h3 {
  margin: 4px 0 0;
  font-size: 15px;
}

.raw-json {
  max-height: 52vh;
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
