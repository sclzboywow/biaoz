<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { api, type SourceCategory, type TrustedSource } from '../../api'
import { dateTimeFormatter } from '../../utils/tableFormatters'

const route = useRoute()
const source = ref<TrustedSource | null>(null)
const categories = ref<SourceCategory[]>([])
const loading = ref(false)

const sourceId = computed(() => Number(route.params.id))

async function loadDetail() {
  if (!sourceId.value) return
  loading.value = true
  try {
    const [sourcesRes, categoriesRes] = await Promise.all([
      api.get<TrustedSource[]>('/trusted-sources'),
      api.get<SourceCategory[]>(`/trusted-sources/${sourceId.value}/categories`),
    ])
    source.value = sourcesRes.data.find((item) => item.id === sourceId.value) || null
    categories.value = categoriesRes.data
  } finally {
    loading.value = false
  }
}

onMounted(loadDetail)
</script>

<template>
  <section v-loading="loading" class="panel">
    <div class="toolbar">
      <h2>{{ source?.source_name || '来源详情' }}</h2>
      <el-button :icon="Refresh" @click="loadDetail">刷新</el-button>
    </div>

    <el-descriptions v-if="source" :column="2" border>
      <el-descriptions-item label="来源名称">{{ source.source_name }}</el-descriptions-item>
      <el-descriptions-item label="基础 URL">{{ source.base_url }}</el-descriptions-item>
      <el-descriptions-item label="信任等级">{{ source.trust_level }}</el-descriptions-item>
      <el-descriptions-item label="信任分">{{ source.trust_score }}</el-descriptions-item>
      <el-descriptions-item label="来源类型">{{ source.source_type }}</el-descriptions-item>
      <el-descriptions-item label="来源角色">{{ source.source_role || '-' }}</el-descriptions-item>
      <el-descriptions-item label="域名">{{ source.domain || '-' }}</el-descriptions-item>
      <el-descriptions-item label="治理状态">{{ source.governance_status || '-' }}</el-descriptions-item>
      <el-descriptions-item label="健康分">{{ source.source_health_score ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="启用">{{ source.enabled ? '是' : '否' }}</el-descriptions-item>
      <el-descriptions-item label="备注" :span="2">{{ source.remark || '-' }}</el-descriptions-item>
    </el-descriptions>

    <h3 class="section-title">分类列表</h3>
    <el-table :data="categories" height="calc(100vh - 420px)">
      <el-table-column prop="source_category_id" label="sublibID" width="100" />
      <el-table-column prop="category_path" label="分类路径" min-width="360" show-overflow-tooltip />
      <el-table-column prop="category_name" label="分类名称" min-width="200" show-overflow-tooltip />
      <el-table-column prop="resource_count" label="资源数" width="90" />
      <el-table-column prop="sync_status" label="同步状态" width="110" />
      <el-table-column prop="last_sync_finished_at" label="最后完成" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
      <el-table-column prop="last_sync_error" label="错误" min-width="180" show-overflow-tooltip />
    </el-table>
  </section>
</template>

<style scoped>
.section-title {
  margin: 20px 0 12px;
  font-size: 15px;
}
</style>
