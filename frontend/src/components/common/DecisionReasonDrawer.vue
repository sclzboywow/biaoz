<script setup lang="ts">
import { ref, watch } from 'vue'
import { api, type ResourceChain } from '../../api'
import { formatDateTime } from '../../utils/formatters'
import RiskLevelTag from '../governance/RiskLevelTag.vue'
import StatusTag from '../governance/StatusTag.vue'

const props = defineProps<{ visible: boolean; resourceId?: number }>()
const emit = defineEmits<{ 'update:visible': [value: boolean] }>()

const loading = ref(false)
const resource = ref<ResourceChain['resource'] | null>(null)

async function loadResource() {
  if (props.resourceId == null) {
    resource.value = null
    return
  }
  loading.value = true
  try {
    const res = await api.get<ResourceChain>(`/standard-resources/${props.resourceId}/chain`)
    resource.value = res.data.resource
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.visible, props.resourceId],
  ([visible]) => {
    if (visible) loadResource()
  },
)
</script>

<template>
  <el-drawer :model-value="visible" title="自动决策说明" size="560px" @update:model-value="emit('update:visible', $event)">
    <div v-loading="loading">
      <template v-if="resource">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="标准编号">{{ resource.standard_no }}</el-descriptions-item>
          <el-descriptions-item label="标准名称">{{ resource.standard_name }}</el-descriptions-item>
          <el-descriptions-item label="自动决策"><StatusTag :status="resource.auto_decision" /></el-descriptions-item>
          <el-descriptions-item label="置信度">{{ resource.confidence_score ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="风险等级"><RiskLevelTag :level="resource.risk_level" /></el-descriptions-item>
          <el-descriptions-item label="决策原因">{{ resource.decision_reason || '-' }}</el-descriptions-item>
          <el-descriptions-item label="最近治理">{{ formatDateTime(resource.last_governed_at) }}</el-descriptions-item>
        </el-descriptions>
      </template>
      <el-empty v-else description="暂无决策信息" />
    </div>
  </el-drawer>
</template>
