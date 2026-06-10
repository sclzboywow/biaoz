<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import {
  api,
  type Page,
  type SourceCategory,
  type StandardResource,
  type TrustedSource,
} from '../../api'
import CursorPager from '../../components/governance/CursorPager.vue'
import {
  applyPageResultWithQuery,
  createCursorPager,
  nextCursorPage,
  pageParams,
  prevCursorPage,
  resetCursorPager,
} from '../../composables/useCursorPager'
import { useObjectNavigation } from '../../composables/useObjectNavigation'
import { usePermissions } from '../../composables/usePermissions'
import { dateFormatter, dateTimeFormatter } from '../../utils/tableFormatters'

const { goStandardDetail } = useObjectNavigation()
const { can } = usePermissions()

const trustedSources = ref<TrustedSource[]>([])
const sourceCategories = ref<SourceCategory[]>([])
const trustedResources = ref<StandardResource[]>([])
const resourceTotal = ref(0)
const selectedTrustedSourceId = ref<number | undefined>()
const selectedSourceCategoryId = ref<string | undefined>()
const trustedResourceActiveTab = ref('resources')
const syncingTrustedSource = ref(false)
const discoveringCategories = ref(false)
const syncingPendingCategories = ref(false)
const trustedResourceTableHeight = 'calc(100vh - 330px)'
const pageSizeOptions = [20, 50, 100, 200]

const resourceQuery = reactive({ page: 1, page_size: 50, q: '', source_status: '', resource_type: '' })
const resourcePager = createCursorPager()

async function loadTrustedSources() {
  const res = await api.get<TrustedSource[]>('/trusted-sources')
  trustedSources.value = res.data
  if (!res.data.some((item) => item.id === selectedTrustedSourceId.value)) {
    selectedTrustedSourceId.value = res.data[0]?.id
  }
  if (selectedTrustedSourceId.value) {
    await loadSourceCategories()
  } else {
    sourceCategories.value = []
    selectedSourceCategoryId.value = undefined
  }
}

async function loadSourceCategories() {
  if (!selectedTrustedSourceId.value) {
    sourceCategories.value = []
    selectedSourceCategoryId.value = undefined
    return
  }
  const res = await api.get<SourceCategory[]>(`/trusted-sources/${selectedTrustedSourceId.value}/categories`)
  sourceCategories.value = res.data
  if (!sourceCategories.value.some((item) => item.source_category_id === selectedSourceCategoryId.value)) {
    selectedSourceCategoryId.value = undefined
  }
}

async function loadTrustedResources() {
  if (!trustedSources.value.length) {
    await loadTrustedSources()
  }
  if (selectedTrustedSourceId.value) {
    await loadSourceCategories()
  }
  const res = await api.get<Page<StandardResource>>('/standard-resources/page', {
    params: {
      ...pageParams(resourceQuery, resourcePager),
      source_id: selectedTrustedSourceId.value,
      source_category_id: selectedSourceCategoryId.value,
    },
  })
  trustedResources.value = res.data.items
  resourceTotal.value = res.data.total
  applyPageResultWithQuery(resourceQuery, resourcePager, res.data)
}

async function resetTrustedResources() {
  resetCursorPager(resourcePager)
  await loadTrustedResources()
}

async function discoverSourceCategories() {
  if (!selectedTrustedSourceId.value) {
    ElMessage.warning('请选择可信源')
    return
  }
  discoveringCategories.value = true
  try {
    const res = await api.post(`/trusted-sources/${selectedTrustedSourceId.value}/discover-categories`)
    ElMessage.success(`发现 ${res.data.discovered} 个分类，新增 ${res.data.created} 个，更新 ${res.data.updated} 个`)
    await loadSourceCategories()
  } finally {
    discoveringCategories.value = false
  }
}

async function syncTrustedSource() {
  if (!selectedTrustedSourceId.value) {
    ElMessage.warning('请选择可信源')
    return
  }
  syncingTrustedSource.value = true
  try {
    const res = await api.post('/trusted-sources/sync', {
      source_id: selectedTrustedSourceId.value,
      max_pages: 1,
      include_detail: true,
      category_id: selectedSourceCategoryId.value,
    })
    ElMessage.success(`同步 ${res.data.items} 条，新增 ${res.data.created} 条，更新 ${res.data.updated} 条`)
    await loadTrustedResources()
  } finally {
    syncingTrustedSource.value = false
  }
}

async function syncPendingCategories() {
  if (!selectedTrustedSourceId.value) {
    ElMessage.warning('请选择可信源')
    return
  }
  syncingPendingCategories.value = true
  try {
    const res = await api.post('/trusted-sources/sync', {
      source_id: selectedTrustedSourceId.value,
      max_pages: 10,
      include_detail: false,
      only_pending_categories: true,
      category_limit: 50,
    })
    ElMessage.success(`同步分类 ${res.data.categories} 个，资源 ${res.data.items} 条`)
    await loadSourceCategories()
    await loadTrustedResources()
  } finally {
    syncingPendingCategories.value = false
  }
}

function onRowClick(row: StandardResource) {
  goStandardDetail(row.id)
}

onMounted(loadTrustedResources)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>标准资源主库</h2>
      <div>
        <el-select v-model="selectedTrustedSourceId" placeholder="选择可信源" style="width: 220px; margin-right: 8px" @change="resetTrustedResources">
          <el-option v-for="item in trustedSources" :key="item.id" :label="item.source_name" :value="item.id" />
        </el-select>
        <el-button :icon="Refresh" @click="loadTrustedResources">刷新</el-button>
        <el-button v-if="can('settings')" :loading="discoveringCategories" @click="discoverSourceCategories">发现分类</el-button>
        <el-button v-if="can('settings')" :loading="syncingPendingCategories" @click="syncPendingCategories">批量同步待同步分类</el-button>
        <el-button v-if="can('settings')" type="primary" :loading="syncingTrustedSource" @click="syncTrustedSource">同步当前源</el-button>
      </div>
    </div>
    <el-form :inline="true" class="filters">
      <el-form-item label="分类">
        <el-select v-model="selectedSourceCategoryId" clearable filterable placeholder="选择 sublibID" style="width: 360px" @change="resetTrustedResources">
          <el-option v-for="item in sourceCategories" :key="item.id" :label="`${item.source_category_id} ${item.category_path || item.category_name}`" :value="item.source_category_id" />
        </el-select>
      </el-form-item>
      <el-form-item label="查询"><el-input v-model="resourceQuery.q" clearable placeholder="编号、名称、关键词、分类" @keyup.enter="resetTrustedResources" /></el-form-item>
      <el-form-item label="状态"><el-select v-model="resourceQuery.source_status" clearable style="width: 120px"><el-option label="现行" value="现行" /><el-option label="废止" value="废止" /></el-select></el-form-item>
      <el-form-item><el-button :icon="Search" @click="resetTrustedResources">查询</el-button></el-form-item>
    </el-form>
    <el-tabs v-model="trustedResourceActiveTab" class="content-tabs">
      <el-tab-pane label="资源列表" name="resources">
        <el-table :data="trustedResources" :height="trustedResourceTableHeight" @row-click="onRowClick">
          <el-table-column prop="standard_no" label="编号" width="160" />
          <el-table-column prop="standard_name" label="名称" min-width="320" show-overflow-tooltip />
          <el-table-column prop="resource_type" label="资源类型" width="140" />
          <el-table-column prop="source_status" label="可信源状态" width="120" />
          <el-table-column prop="matched_document_count" label="匹配文件" width="100" />
          <el-table-column prop="publish_date" label="发布日期" width="120" :formatter="dateFormatter" show-overflow-tooltip />
          <el-table-column prop="effective_date" label="实施日期" width="120" :formatter="dateFormatter" show-overflow-tooltip />
          <el-table-column prop="abolish_date" label="废止日期" width="120" :formatter="dateFormatter" show-overflow-tooltip />
          <el-table-column prop="source_category_path" label="分类路径" min-width="260" show-overflow-tooltip />
        </el-table>
        <CursorPager
          :pager="resourcePager"
          :total="resourceTotal"
          :page-size-options="pageSizeOptions"
          @prev="prevCursorPage(resourcePager, loadTrustedResources)"
          @next="nextCursorPage(resourcePager, loadTrustedResources)"
          @page-size-change="(size) => { resourceQuery.page_size = size; resetTrustedResources() }"
        />
      </el-tab-pane>
      <el-tab-pane label="分类同步队列" name="queue">
        <el-table :data="sourceCategories" :height="trustedResourceTableHeight">
          <el-table-column prop="source_category_id" label="sublibID" width="100" />
          <el-table-column prop="category_path" label="分类路径" min-width="360" show-overflow-tooltip />
          <el-table-column prop="sync_status" label="同步状态" width="110" />
          <el-table-column prop="last_synced_page" label="页数" width="80" />
          <el-table-column prop="last_sync_finished_at" label="最后完成" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
          <el-table-column prop="last_sync_error" label="错误" min-width="180" show-overflow-tooltip />
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>
