<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { api, type SourceHealthItem, type SourceHealthPage } from '../../api'
import CursorPager from '../../components/governance/CursorPager.vue'
import SourceHealthScore from '../../components/governance/SourceHealthScore.vue'
import StatusTag from '../../components/governance/StatusTag.vue'
import { applyPageResult, createCursorPager, nextCursorPage, prevCursorPage, resetCursorPager } from '../../composables/useCursorPager'
import { useObjectNavigation } from '../../composables/useObjectNavigation'

const { goSourceMaster } = useObjectNavigation()

const items = ref<SourceHealthItem[]>([])
const total = ref(0)
const loading = ref(false)
const pager = createCursorPager()
const query = reactive({
  trust_level: '',
  source_role: '',
  governance_status: '',
  health_min: undefined as number | undefined,
  health_max: undefined as number | undefined,
  enabled: undefined as boolean | undefined,
})

async function loadItems() {
  loading.value = true
  try {
    const res = await api.get<SourceHealthPage>('/source-governance/source-health/page', {
      params: {
        cursor: pager.cursors[pager.page - 1] ?? undefined,
        page_size: 50,
        trust_level: query.trust_level || undefined,
        source_role: query.source_role || undefined,
        governance_status: query.governance_status || undefined,
        health_min: query.health_min,
        health_max: query.health_max,
        enabled: query.enabled,
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

function onRowClick(row: SourceHealthItem) {
  goSourceMaster(row.id)
}

onMounted(loadItems)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>来源健康度</h2>
      <el-button :icon="Refresh" :loading="loading" @click="loadItems">刷新</el-button>
    </div>
    <el-form :inline="true" class="filters">
      <el-form-item label="等级"><el-select v-model="query.trust_level" clearable style="width: 100px"><el-option label="A+" value="A+" /><el-option label="A" value="A" /><el-option label="B" value="B" /></el-select></el-form-item>
      <el-form-item label="角色"><el-input v-model="query.source_role" clearable style="width: 120px" /></el-form-item>
      <el-form-item label="治理状态"><el-input v-model="query.governance_status" clearable style="width: 120px" /></el-form-item>
      <el-form-item label="健康分"><el-input-number v-model="query.health_min" :min="0" :max="100" /> - <el-input-number v-model="query.health_max" :min="0" :max="100" /></el-form-item>
      <el-form-item label="启用"><el-select v-model="query.enabled" clearable style="width: 100px"><el-option label="是" :value="true" /><el-option label="否" :value="false" /></el-select></el-form-item>
      <el-form-item><el-button :icon="Search" @click="resetQuery">查询</el-button></el-form-item>
    </el-form>
    <el-table v-loading="loading" :data="items" height="calc(100vh - 280px)" @row-click="onRowClick">
      <el-table-column prop="source_name" label="来源名称" min-width="160" show-overflow-tooltip />
      <el-table-column prop="source_role" label="来源角色" width="100" />
      <el-table-column prop="trust_level" label="来源等级" width="90" />
      <el-table-column prop="domain" label="来源域名" min-width="160" show-overflow-tooltip />
      <el-table-column label="健康分" width="160"><template #default="{ row }"><SourceHealthScore :score="row.health_score" /></template></el-table-column>
      <el-table-column prop="capture_success_rate" label="抓取成功率" width="110" />
      <el-table-column prop="pdf_valid_rate" label="PDF有效率" width="110" />
      <el-table-column prop="ocr_success_rate" label="OCR成功率" width="110" />
      <el-table-column label="治理状态" width="120"><template #default="{ row }"><StatusTag :status="row.governance_status" /></template></el-table-column>
      <el-table-column prop="suggested_action" label="建议动作" width="120" />
    </el-table>
    <CursorPager :pager="pager" :total="total" @prev="prevCursorPage(pager, loadItems)" @next="nextCursorPage(pager, loadItems)" />
  </section>
</template>
