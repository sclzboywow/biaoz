<script setup lang="ts">
import type { CursorPager } from '../../composables/useCursorPager'

defineProps<{
  pager: CursorPager
  total: number
  pageSizeOptions?: number[]
}>()

const emit = defineEmits<{
  prev: []
  next: []
  pageSizeChange: [size: number]
}>()
</script>

<template>
  <div class="cursor-pager">
    <span>Total {{ total }}</span>
    <slot name="extra" />
    <el-select v-if="pageSizeOptions?.length" style="width: 132px" @change="emit('pageSizeChange', $event)">
      <el-option v-for="size in pageSizeOptions" :key="size" :label="`${size}/page`" :value="size" />
    </el-select>
    <el-button :disabled="pager.page <= 1" @click="emit('prev')">上一页</el-button>
    <span>第 {{ pager.page }} 页</span>
    <el-button :disabled="!pager.hasMore" @click="emit('next')">下一页</el-button>
  </div>
</template>
