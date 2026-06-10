<script setup lang="ts">
defineProps<{ score: number }>()
</script>

<template>
  <div class="health-score">
    <el-progress :percentage="Math.max(0, Math.min(100, score))" :stroke-width="10" :color="score >= 80 ? '#67c23a' : score >= 50 ? '#e6a23c' : '#f56c6c'" />
    <span>{{ score }}</span>
  </div>
</template>

<style scoped>
.health-score {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 120px;
}
.health-score :deep(.el-progress) {
  flex: 1;
}
</style>
