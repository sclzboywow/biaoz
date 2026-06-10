<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api, type StorageBrowse, type StorageStatus, type SystemSetting } from '../../api'
import { usePermissions } from '../../composables/usePermissions'
import { dateTimeFormatter } from '../../utils/tableFormatters'

const { can } = usePermissions()

const systemSettings = ref<SystemSetting[]>([])
const storageStatus = ref<StorageStatus | null>(null)
const storagePickerVisible = ref(false)
const storageBrowse = ref<StorageBrowse>({ directories: [] })
const plainTableHeight = 'calc(100vh - 170px)'

async function loadSettings() {
  const res = await api.get<SystemSetting[]>('/settings')
  systemSettings.value = res.data
  await loadStorageStatus()
}

async function loadStorageStatus() {
  const res = await api.get<StorageStatus>('/storage/status')
  storageStatus.value = res.data
}

async function updateSetting(key: string, value: string) {
  if (!can('settings')) {
    ElMessage.warning('当前角色无权修改系统设置')
    return
  }
  await api.patch(`/settings/${key}`, { value })
  ElMessage.success('设置已保存')
  await loadSettings()
}

async function chooseStorageRoot() {
  storagePickerVisible.value = true
  await browseStorage()
}

async function browseStorage(path?: string) {
  const res = await api.get<StorageBrowse>('/storage/browse', { params: path ? { path } : {} })
  storageBrowse.value = res.data
}

async function openStorageDirectory(row: StorageBrowse['directories'][number]) {
  await browseStorage(row.path)
}

async function confirmStorageRoot() {
  if (!storageBrowse.value.path) return
  await updateSetting('storage_root', storageBrowse.value.path)
  storagePickerVisible.value = false
}

onMounted(loadSettings)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>系统设置</h2>
      <el-button :icon="Refresh" @click="loadSettings">刷新</el-button>
    </div>
    <el-alert
      v-if="storageStatus"
      :title="storageStatus.available ? '文件存储可用' : '文件存储不可用'"
      :type="storageStatus.available ? 'success' : 'error'"
      :description="`${storageStatus.message}：${storageStatus.root}`"
      show-icon
      :closable="false"
      class="storage-alert"
    />
    <el-table :data="systemSettings" :height="plainTableHeight">
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
            :step="60"
            :disabled="!can('settings')"
            controls-position="right"
            @change="(value: number | undefined) => updateSetting(row.key, String(value ?? 0))"
          />
          <el-input
            v-else-if="row.value_type === 'secret'"
            :model-value="row.value"
            type="password"
            show-password
            :disabled="!can('settings')"
            @change="(value: string) => updateSetting(row.key, value)"
          />
          <div v-else-if="row.key === 'storage_root'" class="setting-path-control">
            <el-input :model-value="row.value" :disabled="!can('settings')" @change="(value: string) => updateSetting(row.key, value)" />
            <el-button :disabled="!can('settings')" @click="chooseStorageRoot">选择目录</el-button>
          </div>
          <el-input v-else :model-value="row.value" :disabled="!can('settings')" @change="(value: string) => updateSetting(row.key, value)" />
        </template>
      </el-table-column>
      <el-table-column prop="description" label="说明" min-width="320" show-overflow-tooltip />
      <el-table-column prop="updated_at" label="更新时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
    </el-table>
  </section>

  <el-dialog v-model="storagePickerVisible" title="选择文件存储目录" width="720px">
    <div class="storage-picker-path">{{ storageBrowse.path || '本机磁盘' }}</div>
    <div class="storage-picker-actions">
      <el-button @click="browseStorage()">本机磁盘</el-button>
      <el-button :disabled="!storageBrowse.parent" @click="browseStorage(storageBrowse.parent)">上一级</el-button>
      <el-button type="primary" :disabled="!storageBrowse.path" @click="confirmStorageRoot">使用当前目录</el-button>
    </div>
    <el-table :data="storageBrowse.directories" height="360" @row-dblclick="openStorageDirectory">
      <el-table-column prop="name" label="目录" min-width="220" />
      <el-table-column prop="path" label="路径" min-width="420" show-overflow-tooltip />
      <el-table-column label="操作" width="90">
        <template #default="{ row }">
          <el-button size="small" @click="browseStorage(row.path)">打开</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-dialog>
</template>

<style scoped>
.setting-path-control {
  display: flex;
  gap: 8px;
}
.storage-picker-path {
  margin-bottom: 12px;
  font-family: monospace;
}
.storage-picker-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
</style>
