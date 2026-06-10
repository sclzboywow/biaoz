<script setup lang="ts">
import { ref, watch } from 'vue'
import { api, type ProcessAuditLog } from '../../api'
import { formatDateTime } from '../../utils/formatters'

const props = defineProps<{
  visible: boolean
  targetType?: string
  targetId?: number
  processType?: string
  title?: string
}>()

const emit = defineEmits<{ 'update:visible': [value: boolean] }>()
const logs = ref<ProcessAuditLog[]>([])
const loading = ref(false)

async function loadLogs() {
  if (!props.targetType || props.targetId == null) {
    logs.value = []
    return
  }
  loading.value = true
  try {
    const res = await api.get<ProcessAuditLog[]>('/process-audit-logs', {
      params: {
        target_type: props.targetType,
        target_id: props.targetId,
        process_type: props.processType,
        limit: 100,
      },
    })
    logs.value = res.data
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.visible, props.targetType, props.targetId, props.processType],
  ([visible]) => {
    if (visible) loadLogs()
  },
)
</script>

<template>
  <el-drawer :model-value="visible" :title="title || '流程审计日志'" size="640px" @update:model-value="emit('update:visible', $event)">
    <el-table v-loading="loading" :data="logs" height="calc(100vh - 120px)">
      <el-table-column prop="step_name" label="步骤" width="140" show-overflow-tooltip />
      <el-table-column prop="status" label="状态" width="90" />
      <el-table-column prop="message" label="结果" min-width="160" show-overflow-tooltip />
      <el-table-column prop="error_message" label="错误" min-width="160" show-overflow-tooltip />
      <el-table-column prop="created_at" label="时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
    </el-table>
  </el-drawer>
</template>
