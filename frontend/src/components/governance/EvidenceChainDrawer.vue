<script setup lang="ts">
import { ref, watch } from 'vue'
import { api, type DocumentChain, type ResourceChain } from '../../api'

const props = defineProps<{
  visible: boolean
  resourceId?: number
  documentId?: number
  title?: string
}>()

const emit = defineEmits<{ 'update:visible': [value: boolean] }>()
const loading = ref(false)
const resourceChain = ref<ResourceChain | null>(null)
const documentChain = ref<DocumentChain | null>(null)

async function loadChain() {
  loading.value = true
  try {
    resourceChain.value = null
    documentChain.value = null
    if (props.resourceId) {
      const res = await api.get<ResourceChain>(`/standard-resources/${props.resourceId}/chain`)
      resourceChain.value = res.data
    } else if (props.documentId) {
      const res = await api.get<DocumentChain>(`/documents/${props.documentId}/chain`)
      documentChain.value = res.data
    }
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.visible, props.resourceId, props.documentId],
  ([visible]) => {
    if (visible) loadChain()
  },
)
</script>

<template>
  <el-drawer :model-value="visible" :title="title || '证据链'" size="760px" @update:model-value="emit('update:visible', $event)">
    <div v-loading="loading">
      <template v-if="resourceChain">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="标准编号">{{ resourceChain.resource.standard_no }}</el-descriptions-item>
          <el-descriptions-item label="标准名称">{{ resourceChain.resource.standard_name }}</el-descriptions-item>
          <el-descriptions-item label="来源状态">{{ resourceChain.resource.source_status }}</el-descriptions-item>
          <el-descriptions-item label="自动决策">{{ resourceChain.resource.auto_decision || '-' }}</el-descriptions-item>
        </el-descriptions>
        <h4 style="margin-top: 16px">证据记录</h4>
        <el-table :data="resourceChain.evidences" height="220">
          <el-table-column prop="source_name" label="来源" width="120" />
          <el-table-column prop="parsed_status" label="解析状态" width="120" />
          <el-table-column prop="evidence_note" label="说明" min-width="220" show-overflow-tooltip />
        </el-table>
      </template>
      <template v-else-if="documentChain">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="文件名称">{{ documentChain.document.title }}</el-descriptions-item>
          <el-descriptions-item label="标准编号">{{ documentChain.document.standard_no }}</el-descriptions-item>
          <el-descriptions-item label="系统判断">{{ documentChain.document.system_status }}</el-descriptions-item>
          <el-descriptions-item label="人工复核">{{ documentChain.document.manual_status }}</el-descriptions-item>
        </el-descriptions>
        <h4 style="margin-top: 16px">匹配资源</h4>
        <el-table :data="documentChain.resources" height="220">
          <el-table-column prop="standard_no" label="编号" width="140" />
          <el-table-column prop="standard_name" label="名称" min-width="220" show-overflow-tooltip />
          <el-table-column prop="source_status" label="状态" width="100" />
        </el-table>
      </template>
      <el-empty v-else description="暂无证据链数据" />
    </div>
  </el-drawer>
</template>
