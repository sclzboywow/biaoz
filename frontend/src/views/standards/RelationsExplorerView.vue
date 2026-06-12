<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Check, Link, Refresh, Search, View as ViewIcon } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api, type Page, type StandardRelation } from '../../api'
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

const items = ref<StandardRelation[]>([])
const total = ref(0)
const loading = ref(false)
const confirmingId = ref<number | null>(null)
const detailVisible = ref(false)
const selectedRelation = ref<StandardRelation | null>(null)
const pageSizeOptions = [20, 50, 100, 200]
const pager = createCursorPager()
const query = reactive({
  page: 1,
  page_size: 50,
  q: '',
  relation_type: '',
  is_manual_confirmed: undefined as boolean | undefined,
})

const relationTitle = computed(() => {
  if (!selectedRelation.value) return ''
  const left = selectedRelation.value.current_standard_no || '-'
  const right = selectedRelation.value.related_standard_no || '-'
  return `${left} -> ${right}`
})

async function loadItems() {
  loading.value = true
  try {
    const res = await api.get<Page<StandardRelation>>('/standard-relations/page', {
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

function openDetail(row: StandardRelation) {
  selectedRelation.value = row
  detailVisible.value = true
}

function openExternal(url?: string | null) {
  if (!url) return
  window.open(url, '_blank', 'noopener,noreferrer')
}

function openCurrent(row: StandardRelation) {
  if (row.current_standard_resource_id) {
    goStandardDetail(row.current_standard_resource_id)
  }
}

function openRelated(row: StandardRelation) {
  if (row.related_standard_resource_id) {
    goStandardDetail(row.related_standard_resource_id)
  }
}

function openRelationChain(row: StandardRelation) {
  openEvidence(row.current_standard_resource_id || row.related_standard_resource_id)
}

async function confirmRelation(row: StandardRelation) {
  confirmingId.value = row.id
  try {
    await api.patch(`/standard-relations/${row.id}`, { is_manual_confirmed: true })
    ElMessage.success('关系已确认')
    await loadItems()
  } finally {
    confirmingId.value = null
  }
}

onMounted(loadItems)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>替代关系</h2>
      <el-button :icon="Refresh" :loading="loading" @click="loadItems">刷新</el-button>
    </div>

    <el-form :inline="true" class="filters">
      <el-form-item label="查询">
        <el-input v-model="query.q" clearable placeholder="标准号、名称、关系原文、来源 URL" style="width: 360px" @keyup.enter="resetQuery" />
      </el-form-item>
      <el-form-item label="关系类型">
        <el-select v-model="query.relation_type" clearable style="width: 130px">
          <el-option label="替代" value="替代" />
          <el-option label="被替代" value="被替代" />
          <el-option label="引用" value="引用" />
          <el-option label="相关" value="相关" />
        </el-select>
      </el-form-item>
      <el-form-item label="人工确认">
        <el-select v-model="query.is_manual_confirmed" clearable style="width: 130px">
          <el-option label="已确认" :value="true" />
          <el-option label="未确认" :value="false" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :icon="Search" :loading="loading" @click="resetQuery">查询</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="items" height="calc(100vh - 340px)" @row-dblclick="openDetail">
      <el-table-column prop="current_standard_no" label="当前标准" width="170" show-overflow-tooltip />
      <el-table-column prop="current_standard_name" label="当前标准名称" min-width="240" show-overflow-tooltip />
      <el-table-column prop="relation_type" label="关系" width="100" />
      <el-table-column prop="related_standard_no" label="关联标准" width="170" show-overflow-tooltip />
      <el-table-column prop="related_standard_name" label="关联标准名称" min-width="240" show-overflow-tooltip />
      <el-table-column prop="relation_text" label="关系原文" min-width="300" show-overflow-tooltip />
      <el-table-column label="确认" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_manual_confirmed ? 'success' : 'info'">{{ row.is_manual_confirmed ? '已确认' : '未确认' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="discovered_at" label="发现时间" width="170" :formatter="dateTimeFormatter" />
      <el-table-column label="操作" width="330" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button size="small" :icon="ViewIcon" @click.stop="openDetail(row)">详情</el-button>
            <el-button size="small" :disabled="!row.current_standard_resource_id" @click.stop="openCurrent(row)">当前</el-button>
            <el-button size="small" :disabled="!row.related_standard_resource_id" @click.stop="openRelated(row)">关联</el-button>
            <el-button size="small" @click.stop="openRelationChain(row)">链路</el-button>
            <el-button
              size="small"
              type="primary"
              :icon="Check"
              :disabled="row.is_manual_confirmed"
              :loading="confirmingId === row.id"
              @click.stop="confirmRelation(row)"
            >
              确认
            </el-button>
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

  <el-drawer v-model="detailVisible" title="关系详情" size="720px">
    <div v-if="selectedRelation" class="relation-detail">
      <h3>{{ relationTitle }}</h3>
      <dl class="detail-grid">
        <dt>当前标准</dt>
        <dd>{{ selectedRelation.current_standard_no || '-' }}</dd>
        <dt>当前名称</dt>
        <dd>{{ selectedRelation.current_standard_name || '-' }}</dd>
        <dt>关联标准</dt>
        <dd>{{ selectedRelation.related_standard_no || '-' }}</dd>
        <dt>关联名称</dt>
        <dd>{{ selectedRelation.related_standard_name || '-' }}</dd>
        <dt>关系类型</dt>
        <dd>{{ selectedRelation.relation_type }}</dd>
        <dt>人工确认</dt>
        <dd>{{ selectedRelation.is_manual_confirmed ? '已确认' : '未确认' }}</dd>
        <dt>发现时间</dt>
        <dd>{{ selectedRelation.discovered_at }}</dd>
      </dl>
      <div class="detail-links">
        <el-button :disabled="!selectedRelation.current_standard_resource_id" @click="openCurrent(selectedRelation)">当前标准</el-button>
        <el-button :disabled="!selectedRelation.related_standard_resource_id" @click="openRelated(selectedRelation)">关联标准</el-button>
        <el-button @click="openRelationChain(selectedRelation)">证据链</el-button>
        <el-button :icon="Link" :disabled="!selectedRelation.source_url" @click="openExternal(selectedRelation.source_url)">来源页面</el-button>
        <el-button
          type="primary"
          :disabled="selectedRelation.is_manual_confirmed"
          :loading="confirmingId === selectedRelation.id"
          @click="confirmRelation(selectedRelation)"
        >
          确认关系
        </el-button>
      </div>
      <h3>关系原文</h3>
      <pre class="detail-text">{{ selectedRelation.relation_text || '-' }}</pre>
    </div>
  </el-drawer>
</template>

<style scoped>
.relation-detail {
  display: grid;
  gap: 16px;
}

.relation-detail h3 {
  margin: 0;
  font-size: 15px;
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
