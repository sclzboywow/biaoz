<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { api, type GovernanceExceptionItem, type GovernanceExceptionPage } from '../../api'
import CursorPager from '../../components/governance/CursorPager.vue'
import RiskLevelTag from '../../components/governance/RiskLevelTag.vue'
import { applyPageResult, createCursorPager, nextCursorPage, prevCursorPage, resetCursorPager } from '../../composables/useCursorPager'
import { useObjectNavigation } from '../../composables/useObjectNavigation'

const { openEvidence, openAudit } = useObjectNavigation()

const items = ref<GovernanceExceptionItem[]>([])
const total = ref(0)
const loading = ref(false)
const pager = createCursorPager()
const query = reactive({ q: '' })

async function loadItems() {
  loading.value = true
  try {
    const res = await api.get<GovernanceExceptionPage>('/governance/exceptions/page', {
      params: {
        cursor: pager.cursors[pager.page - 1] ?? undefined,
        page_size: 50,
        q: query.q || undefined,
        risk_level: 'high',
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

onMounted(loadItems)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>高风险异常</h2>
      <div class="toolbar-actions">
        <el-input v-model="query.q" clearable placeholder="编号/名称" style="width: 220px" @keyup.enter="resetQuery" />
        <el-button :icon="Search" @click="resetQuery">查询</el-button>
        <el-button :icon="Refresh" @click="loadItems">刷新</el-button>
      </div>
    </div>
    <el-table v-loading="loading" :data="items" height="calc(100vh - 200px)">
      <el-table-column prop="standard_no" label="标准编号" width="150" show-overflow-tooltip />
      <el-table-column prop="standard_name" label="标准名称" min-width="220" show-overflow-tooltip />
      <el-table-column prop="exception_type" label="异常类型" width="180" show-overflow-tooltip />
      <el-table-column label="风险等级" width="100"><template #default="{ row }"><RiskLevelTag :level="row.risk_level" /></template></el-table-column>
      <el-table-column prop="system_suggestion" label="系统建议" min-width="220" show-overflow-tooltip />
      <el-table-column prop="handle_status" label="处理状态" width="110" />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click.stop="openEvidence(row.resource_id)">证据链</el-button>
          <el-button size="small" @click.stop="openAudit('standard_resource', row.resource_id, 'GOVERNANCE_DECISION')">审计</el-button>
        </template>
      </el-table-column>
    </el-table>
    <CursorPager :pager="pager" :total="total" @prev="prevCursorPage(pager, loadItems)" @next="nextCursorPage(pager, loadItems)" />
  </section>
</template>
