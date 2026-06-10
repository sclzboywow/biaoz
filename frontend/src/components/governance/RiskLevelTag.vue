<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ level?: string | null }>()
const type = computed(() => {
  if (props.level === 'high') return 'danger'
  if (props.level === 'medium') return 'warning'
  if (props.level === 'low') return 'success'
  return 'info'
})
</script>

<template>
  <el-tag v-if="level" :type="type" effect="dark">{{ level }}</el-tag>
  <span v-else>-</span>
</template>
