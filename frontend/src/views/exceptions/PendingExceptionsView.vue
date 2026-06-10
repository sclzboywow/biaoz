<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { api, type GovernanceExceptionItem, type GovernanceExceptionPage } from '../../api'
import CursorPager from '../../components/governance/CursorPager.vue'
import { applyPageResult, createCursorPager, nextCursorPage, prevCursorPage, resetCursorPager } from '../../composables/useCursorPager'
import { useObjectNavigation } from '../../composables/useObjectNavigation'

const { openEvidence, openAudit } = useObjectNavigation()

const governanceExceptions = ref<GovernanceExceptionItem[]>([])
const exceptionTotal = ref(0)
const exceptionQuery = reactive({ q: '', risk_level: '' })
const exceptionPager = createCursorPager()
const plainTableHeight = 'calc(100vh - 170px)'

async function loadGovernanceExceptions() {
  const res = await api.get<GovernanceExceptionPage>('/governance/exceptions/page', {
    params: {
      cursor: exceptionPager.cursors[exceptionPager.page - 1] ?? undefined,
      page_size: 50,
      q: exceptionQuery.q || undefined,
      risk_level: exceptionQuery.risk_level || undefined,
    },
  })
  governanceExceptions.value = res.data.items
  exceptionTotal.value = res.data.total
  applyPageResult(exceptionPager, res.data)
}

async function resetGovernanceExceptions() {
  resetCursorPager(exceptionPager)
  await loadGovernanceExceptions()
}

onMounted(loadGovernanceExceptions)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>待处理异常</h2>
      <div class="toolbar-actions">
        <el-input v-model="exceptionQuery.q" clearable placeholder="编号/名称/建议" style="width: 220px" @keyup.enter="resetGovernanceExceptions" />
        <el-select v-model="exceptionQuery.risk_level" clearable placeholder="风险等级" style="width: 130px">
          <el-option label="高" value="high" />
          <el-option label="中" value="medium" />
          <el-option label="低" value="low" />
        </el-select>
        <el-button :icon="Search" @click="resetGovernanceExceptions">查询</el-button>
        <el-button :icon="Refresh" @click="loadGovernanceExceptions">刷新</el-button>
      </div>
    </div>
    <el-table :data="governanceExceptions" :height="plainTableHeight">
      <el-table-column prop="standard_no" label="标准编号" width="150" show-overflow-tooltip />
      <el-table-column prop="standard_name" label="标准名称" min-width="220" show-overflow-tooltip />
      <el-table-column prop="exception_type" label="异常类型" width="180" show-overflow-tooltip />
      <el-table-column prop="risk_level" label="风险等级" width="100" />
      <el-table-column prop="highest_source_level" label="最高来源等级" width="120" />
      <el-table-column prop="conflict_sources" label="冲突来源" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">{{ (row.conflict_sources || []).join('、') || '-' }}</template>
      </el-table-column>
      <el-table-column prop="system_suggestion" label="系统建议" min-width="220" show-overflow-tooltip />
      <el-table-column prop="handle_status" label="处理状态" width="110" />
      <el-table-column prop="confidence_score" label="置信度" width="90" />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click.stop="openEvidence(row.resource_id)">证据链</el-button>
          <el-button size="small" @click.stop="openAudit('standard_resource', row.resource_id, 'GOVERNANCE_DECISION')">流程日志</el-button>
        </template>
      </el-table-column>
    </el-table>
    <CursorPager :pager="exceptionPager" :total="exceptionTotal" @prev="prevCursorPage(exceptionPager, loadGovernanceExceptions)" @next="nextCursorPage(exceptionPager, loadGovernanceExceptions)" />
  </section>
</template>
