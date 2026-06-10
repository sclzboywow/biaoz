<script setup lang="ts">
defineProps<{
  label: string
  value: string | number
  highlight?: 'danger' | 'warning' | 'success' | 'info'
}>()
</script>

<template>
  <div class="metric-card" :class="highlight ? `metric-${highlight}` : ''">
    <div class="metric-label">{{ label }}</div>
    <div class="metric-value">{{ value }}</div>
  </div>
</template>

<style scoped>
.metric-card {
  min-width: 140px;
  padding: 14px 16px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid #ebeef5;
}
.metric-label {
  color: #909399;
  font-size: 13px;
  margin-bottom: 8px;
}
.metric-value {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
}
.metric-danger .metric-value { color: #f56c6c; }
.metric-warning .metric-value { color: #e6a23c; }
.metric-success .metric-value { color: #67c23a; }
.metric-info .metric-value { color: #409eff; }
</style>
