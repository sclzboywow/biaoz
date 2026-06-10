<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { api, type GovernanceSupervisionSummary, type OcrTasksSummary } from '../../api'
import MetricCard from '../../components/governance/MetricCard.vue'

const router = useRouter()
const ocrSummary = ref<OcrTasksSummary | null>(null)
const supervision = ref<GovernanceSupervisionSummary | null>(null)
const loading = ref(false)

async function loadData() {
  loading.value = true
  try {
    const [ocrRes, supRes] = await Promise.all([
      api.get<OcrTasksSummary>('/ocr-tasks/summary'),
      api.get<GovernanceSupervisionSummary>('/governance/supervision/summary'),
    ])
    ocrSummary.value = ocrRes.data
    supervision.value = supRes.data
  } finally {
    loading.value = false
  }
}

function go(name: string) {
  router.push({ name })
}

onMounted(loadData)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>今日任务</h2>
      <el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button>
    </div>
    <div v-if="ocrSummary" class="status-row">
      <MetricCard label="待 OCR" :value="ocrSummary.pending_ocr" highlight="warning" />
      <MetricCard label="运行中" :value="ocrSummary.running" />
      <MetricCard label="今日成功" :value="ocrSummary.success_today" highlight="success" />
      <MetricCard label="OCR 成功率" :value="`${ocrSummary.ocr_success_rate_today}%`" />
      <MetricCard label="PDF 通过率" :value="`${ocrSummary.pdf_pass_rate_today}%`" />
      <MetricCard label="需人工" :value="ocrSummary.need_manual" highlight="warning" />
    </div>
    <div v-if="supervision" class="link-cards">
      <el-card shadow="hover" class="link-card" @click="go('ocr-download-queue')">
        <div class="link-card-title">OCR 下载队列</div>
        <div class="link-card-value">{{ ocrSummary?.pending_ocr ?? 0 }} 待处理</div>
      </el-card>
      <el-card shadow="hover" class="link-card" @click="go('pending-exceptions')">
        <div class="link-card-title">待处理异常</div>
        <div class="link-card-value">{{ supervision.pending_exceptions }} 条</div>
      </el-card>
      <el-card shadow="hover" class="link-card" @click="go('high-risk-exceptions')">
        <div class="link-card-title">高风险异常</div>
        <div class="link-card-value">{{ supervision.high_risk_exceptions }} 条</div>
      </el-card>
      <el-card shadow="hover" class="link-card" @click="go('alerts')">
        <div class="link-card-title">异常提醒</div>
        <div class="link-card-value">{{ supervision.pending_alerts }} 条</div>
      </el-card>
    </div>
  </section>
</template>

<style scoped>
.link-cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-top: 16px;
}
.link-card {
  cursor: pointer;
}
.link-card-title {
  font-size: 14px;
  color: #606266;
}
.link-card-value {
  margin-top: 8px;
  font-size: 22px;
  font-weight: 600;
}
</style>
