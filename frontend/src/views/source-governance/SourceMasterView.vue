<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { api, type TrustedSource } from '../../api'
import { useObjectNavigation } from '../../composables/useObjectNavigation'

const { goSourceMaster } = useObjectNavigation()

const sources = ref<TrustedSource[]>([])
const loading = ref(false)

async function loadSources() {
  loading.value = true
  try {
    const res = await api.get<TrustedSource[]>('/trusted-sources')
    sources.value = res.data
  } finally {
    loading.value = false
  }
}

onMounted(loadSources)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>可信来源主库</h2>
      <el-button :icon="Refresh" :loading="loading" @click="loadSources">刷新</el-button>
    </div>
    <el-table v-loading="loading" :data="sources" height="calc(100vh - 170px)" @row-click="(row: TrustedSource) => goSourceMaster(row.id)">
      <el-table-column prop="source_name" label="来源名称" min-width="200" show-overflow-tooltip />
      <el-table-column prop="base_url" label="基础 URL" min-width="260" show-overflow-tooltip />
      <el-table-column prop="trust_level" label="信任等级" width="100" />
      <el-table-column prop="trust_score" label="信任分" width="90" />
      <el-table-column prop="source_type" label="类型" width="120" />
      <el-table-column prop="source_role" label="角色" width="120" />
      <el-table-column prop="domain" label="域名" width="160" show-overflow-tooltip />
      <el-table-column label="启用" width="80"><template #default="{ row }">{{ row.enabled ? '是' : '否' }}</template></el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click.stop="goSourceMaster(row.id)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>
  </section>
</template>
