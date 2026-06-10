<script setup lang="ts">
import { ref, watch } from 'vue'
import { api, type FileObjectItem } from '../../api'
import { formatDateTime, formatFileSize } from '../../utils/formatters'
import { useObjectNavigation } from '../../composables/useObjectNavigation'

const props = defineProps<{ visible: boolean; fileObjectId?: number }>()
const emit = defineEmits<{ 'update:visible': [value: boolean] }>()

const loading = ref(false)
const item = ref<FileObjectItem | null>(null)
const nav = useObjectNavigation()

async function loadItem() {
  if (props.fileObjectId == null) {
    item.value = null
    return
  }
  loading.value = true
  try {
    const res = await api.get<FileObjectItem>(`/file-objects/${props.fileObjectId}`)
    item.value = res.data
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.visible, props.fileObjectId],
  ([visible]) => {
    if (visible) loadItem()
  },
)
</script>

<template>
  <el-drawer :model-value="visible" title="文件对象详情" size="640px" @update:model-value="emit('update:visible', $event)">
    <div v-loading="loading">
      <template v-if="item">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="file_hash">{{ item.file_hash }}</el-descriptions-item>
          <el-descriptions-item label="文件大小">{{ formatFileSize(item.file_size) }}</el-descriptions-item>
          <el-descriptions-item label="PDF 状态">{{ item.pdf_validation_status || (item.pdf_valid ? '有效' : '无效') }}</el-descriptions-item>
          <el-descriptions-item label="PDF 页数">{{ item.pdf_page_count ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="存储后端">{{ item.storage_backend || '-' }}</el-descriptions-item>
          <el-descriptions-item label="存储位置">{{ item.local_path || '-' }}</el-descriptions-item>
          <el-descriptions-item label="关联标准数">{{ item.linked_standard_count }}</el-descriptions-item>
          <el-descriptions-item label="关联来源数">{{ item.linked_source_count }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatDateTime(item.created_at) }}</el-descriptions-item>
        </el-descriptions>
        <div style="margin-top: 16px">
          <el-button type="primary" @click="nav.goFileArchive()">查看文件归档库</el-button>
        </div>
      </template>
      <el-empty v-else description="暂无文件对象" />
    </div>
  </el-drawer>
</template>
