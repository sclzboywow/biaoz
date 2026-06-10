<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status?: string | null }>()

const type = computed(() => {
  const value = (props.status || '').toLowerCase()
  if (['archived', 'auto_confirmed', '正常', '已画像', '高优先级采集'].some(v => value.includes(v.toLowerCase()))) return 'success'
  if (['pending', 'running', '待复核', '需 ocr', 'need_review', 'need_manual'].some(v => value.includes(v))) return 'warning'
  if (['failed', 'invalid', 'error', '黑名单', '失效', 'pdf_invalid'].some(v => value.includes(v))) return 'danger'
  if (['skipped', '只作线索', '低优先级采集'].some(v => value.includes(v))) return 'info'
  return ''
})
</script>

<template>
  <el-tag v-if="status" :type="type || undefined" effect="light">{{ status }}</el-tag>
  <span v-else>-</span>
</template>
