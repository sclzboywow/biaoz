<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api, type GovernanceExceptionItem, type GovernanceExceptionPage, type SupervisionSummaryEnhanced } from '../../api'
import AuditLogDrawer from '../../components/governance/AuditLogDrawer.vue'
import CursorPager from '../../components/governance/CursorPager.vue'
import EvidenceChainDrawer from '../../components/governance/EvidenceChainDrawer.vue'
import MetricCard from '../../components/governance/MetricCard.vue'
import RiskLevelTag from '../../components/governance/RiskLevelTag.vue'
import { applyPageResult, createCursorPager, nextCursorPage, prevCursorPage, resetCursorPager } from '../../composables/useCursorPager'

const summary = ref<SupervisionSummaryEnhanced | null>(null)
const items = ref<GovernanceExceptionItem[]>([])
const total = ref(0)
const loading = ref(false)
const runningDecisions = ref(false)
const decisionLimit = ref(100)
const pager = createCursorPager()
const query = reactive({ q: '', risk_level: '' })
const auditVisible = ref(false)
const auditTargetId = ref<number>()
const chainVisible = ref(false)
const chainResourceId = ref<number>()

async function loadSummary() {
  const res = await api.get<SupervisionSummaryEnhanced>('/governance/supervision/summary')
  summary.value = res.data
}

async function loadItems() {
  loading.value = true
  try {
    const res = await api.get<GovernanceExceptionPage>('/governance/exceptions/page', {
      params: {
        cursor: pager.cursors[pager.page - 1] ?? undefined,
        page_size: 50,
        q: query.q || undefined,
        risk_level: query.risk_level || undefined,
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

async function runDecisions(dryRun: boolean) {
  runningDecisions.value = true
  try {
    const res = await api.post('/governance/run-decisions', { limit: decisionLimit.value, only_unprocessed: true, dry_run: dryRun })
    ElMessage.success(dryRun ? `试跑完成：处理 ${res.data.processed}` : `决策完成：需复核 ${res.data.need_review}`)
    if (!dryRun) {
      await loadSummary()
      await loadItems()
    }
  } finally {
    runningDecisions.value = false
  }
}

function openAudit(row: GovernanceExceptionItem) {
  auditTargetId.value = row.resource_id
  auditVisible.value = true
}

function openChain(row: GovernanceExceptionItem) {
  chainResourceId.value = row.resource_id
  chainVisible.value = true
}

onMounted(async () => {
  await Promise.all([loadSummary(), loadItems()])
})
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>自动监督中心</h2>
      <div class="toolbar-actions">
        <el-input-number v-model="decisionLimit" :min="10" :max="5000" :step="100" />
        <el-button :icon="Refresh" @click="loadSummary(); loadItems()">刷新</el-button>
        <el-button :loading="runningDecisions" @click="runDecisions(true)">试跑决策</el-button>
        <el-button type="primary" :loading="runningDecisions" @click="runDecisions(false)">执行决策</el-button>
      </div>
    </div>
    <div v-if="summary" class="status-row">
      <MetricCard label="自动确认" :value="summary.auto_confirmed" highlight="success" />
      <MetricCard label="自动合并" :value="summary.auto_merged" />
      <MetricCard label="自动降级" :value="summary.auto_downgraded" />
      <MetricCard label="自动拒绝" :value="summary.auto_rejected" />
      <MetricCard label="需人工处理" :value="summary.need_review_count" highlight="danger" />
      <MetricCard label="高风险异常" :value="summary.high_risk_exceptions" highlight="danger" />
      <MetricCard label="状态冲突" :value="summary.status_conflict_count" highlight="warning" />
      <MetricCard label="文件异常" :value="summary.file_anomaly_count" highlight="warning" />
      <MetricCard label="OCR 异常" :value="summary.ocr_anomaly_count" highlight="warning" />
    </div>
    <el-form :inline="true" class="filters" style="margin-top: 12px">
      <el-form-item label="查询"><el-input v-model="query.q" clearable @keyup.enter="resetQuery" /></el-form-item>
      <el-form-item label="风险"><el-select v-model="query.risk_level" clearable style="width: 120px"><el-option label="high" value="high" /><el-option label="medium" value="medium" /><el-option label="low" value="low" /></el-select></el-form-item>
      <el-form-item><el-button :icon="Search" @click="resetQuery">查询</el-button></el-form-item>
    </el-form>
    <el-table v-loading="loading" :data="items" height="calc(100vh - 360px)">
      <el-table-column prop="standard_no" label="标准编号" width="140" show-overflow-tooltip />
      <el-table-column prop="standard_name" label="标准名称" min-width="220" show-overflow-tooltip />
      <el-table-column prop="exception_type" label="异常类型" width="180" show-overflow-tooltip />
      <el-table-column label="风险等级" width="100"><template #default="{ row }"><RiskLevelTag :level="row.risk_level" /></template></el-table-column>
      <el-table-column prop="highest_source_level" label="最高权重来源" width="120" />
      <el-table-column label="冲突来源" min-width="160"><template #default="{ row }">{{ (row.conflict_sources || []).join('、') || '-' }}</template></el-table-column>
      <el-table-column prop="system_suggestion" label="系统建议" min-width="220" show-overflow-tooltip />
      <el-table-column prop="handle_status" label="处理状态" width="110" />
      <el-table-column label="操作" width="320" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button size="small" type="success">确认建议</el-button>
            <el-button size="small" @click="openChain(row)">证据链</el-button>
            <el-button size="small" @click="openAudit(row)">流程日志</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
    <CursorPager :pager="pager" :total="total" @prev="prevCursorPage(pager, loadItems)" @next="nextCursorPage(pager, loadItems)" />
    <AuditLogDrawer v-model:visible="auditVisible" target-type="standard_resource" :target-id="auditTargetId" process-type="GOVERNANCE_DECISION" />
    <EvidenceChainDrawer v-model:visible="chainVisible" :resource-id="chainResourceId" />
  </section>
</template>
