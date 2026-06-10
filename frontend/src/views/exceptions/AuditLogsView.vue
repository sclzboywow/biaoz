<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { api, type ProcessAuditLog } from '../../api'
import { useObjectNavigation } from '../../composables/useObjectNavigation'
import { formatDateTime } from '../../utils/formatters'

const { openAudit, goStandardDetail } = useObjectNavigation()

const logs = ref<ProcessAuditLog[]>([])
const loading = ref(false)
const query = reactive({
  process_type: '',
  target_type: '',
  status: '',
  q: '',
})

async function loadLogs() {
  loading.value = true
  try {
    const res = await api.get<ProcessAuditLog[]>('/process-audit-logs', {
      params: {
        process_type: query.process_type || undefined,
        target_type: query.target_type || undefined,
        status: query.status || undefined,
        q: query.q || undefined,
        limit: 200,
      },
    })
    logs.value = res.data
  } finally {
    loading.value = false
  }
}

function onRowClick(row: ProcessAuditLog) {
  if (row.target_type && row.target_id != null) {
    if (row.target_type === 'standard_resource') {
      goStandardDetail(row.target_id, 'audit')
    } else {
      openAudit(row.target_type, row.target_id, row.process_type || undefined)
    }
  }
}

onMounted(loadLogs)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>流程审计日志</h2>
      <el-button :icon="Refresh" :loading="loading" @click="loadLogs">刷新</el-button>
    </div>
    <el-form :inline="true" class="filters">
      <el-form-item label="流程类型"><el-input v-model="query.process_type" clearable style="width: 160px" /></el-form-item>
      <el-form-item label="目标类型"><el-input v-model="query.target_type" clearable style="width: 140px" /></el-form-item>
      <el-form-item label="状态"><el-input v-model="query.status" clearable style="width: 120px" /></el-form-item>
      <el-form-item label="查询"><el-input v-model="query.q" clearable style="width: 200px" @keyup.enter="loadLogs" /></el-form-item>
      <el-form-item><el-button :icon="Search" @click="loadLogs">查询</el-button></el-form-item>
    </el-form>
    <el-table v-loading="loading" :data="logs" height="calc(100vh - 260px)" @row-click="onRowClick">
      <el-table-column prop="process_name" label="流程" width="140" show-overflow-tooltip />
      <el-table-column prop="process_type" label="类型" width="140" show-overflow-tooltip />
      <el-table-column prop="step_name" label="步骤" width="140" show-overflow-tooltip />
      <el-table-column prop="target_type" label="目标类型" width="120" />
      <el-table-column prop="target_id" label="目标ID" width="90" />
      <el-table-column prop="status" label="状态" width="90" />
      <el-table-column prop="message" label="结果" min-width="200" show-overflow-tooltip />
      <el-table-column prop="error_message" label="错误" min-width="160" show-overflow-tooltip />
      <el-table-column label="时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
    </el-table>
  </section>
</template>
