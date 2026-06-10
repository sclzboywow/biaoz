<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api, type SystemSetting } from '../../api'
import { usePermissions } from '../../composables/usePermissions'
import { dateTimeFormatter } from '../../utils/tableFormatters'

const route = useRoute()
const { can } = usePermissions()

const allSettings = ref<SystemSetting[]>([])
const loading = ref(false)

const prefix = computed(() => String(route.meta.settingKeys || ''))

const filteredSettings = computed(() => {
  if (!prefix.value) return allSettings.value
  return allSettings.value.filter((item) => item.key.startsWith(prefix.value))
})

const sectionTitle = computed(() => String(route.meta.title || '设置'))

async function loadSettings() {
  loading.value = true
  try {
    const res = await api.get<SystemSetting[]>('/settings')
    allSettings.value = res.data
  } finally {
    loading.value = false
  }
}

async function updateSetting(key: string, value: string) {
  if (!can('settings')) {
    ElMessage.warning('当前角色无权修改设置')
    return
  }
  await api.patch(`/settings/${key}`, { value })
  ElMessage.success('设置已保存')
  await loadSettings()
}

onMounted(loadSettings)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>{{ sectionTitle }}</h2>
      <el-button :icon="Refresh" :loading="loading" @click="loadSettings">刷新</el-button>
    </div>
    <el-table v-loading="loading" :data="filteredSettings" height="calc(100vh - 170px)">
      <el-table-column prop="label" label="配置项" width="220" />
      <el-table-column prop="key" label="键" width="220" />
      <el-table-column label="值" width="260">
        <template #default="{ row }">
          <el-switch
            v-if="row.value_type === 'bool'"
            :model-value="row.value === 'true'"
            :disabled="!can('settings')"
            @change="(value: boolean) => updateSetting(row.key, value ? 'true' : 'false')"
          />
          <el-input-number
            v-else-if="row.value_type === 'int'"
            :model-value="Number(row.value || 0)"
            :min="0"
            :disabled="!can('settings')"
            controls-position="right"
            @change="(value: number | undefined) => updateSetting(row.key, String(value ?? 0))"
          />
          <el-input v-else :model-value="row.value" :disabled="!can('settings')" @change="(value: string) => updateSetting(row.key, value)" />
        </template>
      </el-table-column>
      <el-table-column prop="description" label="说明" min-width="320" show-overflow-tooltip />
      <el-table-column prop="updated_at" label="更新时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
    </el-table>
  </section>
</template>
