<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { api, type GovernanceDashboardSummary } from '../../api'
import MetricCard from '../../components/governance/MetricCard.vue'
import { distributionEntries } from '../../utils/formatters'

const summary = ref<GovernanceDashboardSummary | null>(null)
const loading = ref(false)

async function loadSummary() {
  loading.value = true
  try {
    const res = await api.get<GovernanceDashboardSummary>('/dashboard/governance-summary')
    summary.value = res.data
  } finally {
    loading.value = false
  }
}

onMounted(loadSummary)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>治理总览</h2>
      <el-button :icon="Refresh" :loading="loading" @click="loadSummary">刷新</el-button>
    </div>
    <div v-if="summary" class="status-row">
      <MetricCard label="URL 总数" :value="summary.url_total" />
      <MetricCard label="已画像 URL" :value="summary.profiled_url_count" />
      <MetricCard label="未治理 URL" :value="summary.ungoverned_url_count" highlight="warning" />
      <MetricCard label="官方来源" :value="summary.official_source_count" />
      <MetricCard label="低可信来源" :value="summary.low_trust_source_count" highlight="warning" />
      <MetricCard label="重复 URL" :value="summary.duplicate_url_count" />
      <MetricCard label="失效 URL" :value="summary.invalid_url_count" highlight="danger" />
      <MetricCard label="需 OCR" :value="summary.need_ocr_count" highlight="warning" />
      <MetricCard label="自动确认" :value="summary.auto_confirmed_count" highlight="success" />
      <MetricCard label="需人工处理" :value="summary.need_manual_count" highlight="danger" />
      <MetricCard label="今日 OCR 成功" :value="summary.ocr_success_today" highlight="success" />
      <MetricCard label="今日 PDF 校验失败" :value="summary.pdf_invalid_today" highlight="danger" />
    </div>
    <div v-if="summary" class="distribution-grid">
      <div class="distribution-card">
        <h3>URL 类型分布</h3>
        <div v-for="[key, count] in distributionEntries(summary.distributions.url_type)" :key="key" class="distribution-row">
          <span>{{ key }}</span><strong>{{ count }}</strong>
        </div>
      </div>
      <div class="distribution-card">
        <h3>来源质量分布</h3>
        <div v-for="[key, count] in distributionEntries(summary.distributions.source_quality)" :key="key" class="distribution-row">
          <span>{{ key }}</span><strong>{{ count }}</strong>
        </div>
      </div>
      <div class="distribution-card">
        <h3>治理状态分布</h3>
        <div v-for="[key, count] in distributionEntries(summary.distributions.governance_status)" :key="key" class="distribution-row">
          <span>{{ key }}</span><strong>{{ count }}</strong>
        </div>
      </div>
      <div class="distribution-card">
        <h3>异常风险分布</h3>
        <div v-for="[key, count] in distributionEntries(summary.distributions.risk)" :key="key" class="distribution-row">
          <span>{{ key }}</span><strong>{{ count }}</strong>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.distribution-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-top: 16px;
}
.distribution-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  padding: 16px;
}
.distribution-card h3 {
  margin: 0 0 12px;
  font-size: 15px;
}
.distribution-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px dashed #f0f2f5;
}
</style>
