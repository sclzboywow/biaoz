<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import {
  api,
  type Page,
  type ResourceDownloadCaptchaChallenge,
  type StandardResource,
  type UrlCheckResult,
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
import { dateFormatter } from '../../utils/tableFormatters'

const { goStandardDetail } = useObjectNavigation()

const standardSearchResources = ref<StandardResource[]>([])
const standardSearchTotal = ref(0)
const standardSearchTableHeight = 'calc(100vh - 340px)'
const pageSizeOptions = [20, 50, 100, 200]
const standardSearchQuery = reactive({ page: 1, page_size: 50, q: '', source_status: '', resource_type: '' })
const standardSearchPager = createCursorPager()

const showResourceDownloadDialog = ref(false)
const selectedDownloadResource = ref<StandardResource | null>(null)
const captchaChallenge = ref<ResourceDownloadCaptchaChallenge | null>(null)
const captchaCode = ref('')
const downloadCaptchaLoadingId = ref<number | null>(null)
const resourceDownloadSubmitting = ref(false)

async function loadStandardSearch() {
  const res = await api.get<Page<StandardResource>>('/standard-resources/page', {
    params: pageParams(standardSearchQuery, standardSearchPager),
  })
  standardSearchResources.value = res.data.items
  standardSearchTotal.value = res.data.total
  applyPageResultWithQuery(standardSearchQuery, standardSearchPager, res.data)
}

async function resetStandardSearch() {
  resetCursorPager(standardSearchPager)
  await loadStandardSearch()
}

function onRowClick(row: StandardResource) {
  goStandardDetail(row.id)
}

function captchaImageSrc() {
  if (!captchaChallenge.value) return ''
  return `data:${captchaChallenge.value.captcha_content_type};base64,${captchaChallenge.value.captcha_image_base64}`
}

async function openResourceDownload(row: StandardResource) {
  if (!row.pdf_trial_url) {
    ElMessage.warning('该来源暂未采集到可下载的官方全文入口')
    return
  }
  selectedDownloadResource.value = row
  captchaCode.value = ''
  showResourceDownloadDialog.value = true
  await refreshResourceCaptcha()
}

async function refreshResourceCaptcha() {
  if (!selectedDownloadResource.value) return
  downloadCaptchaLoadingId.value = selectedDownloadResource.value.id
  try {
    const res = await api.post<ResourceDownloadCaptchaChallenge>(`/standard-resources/${selectedDownloadResource.value.id}/download-captcha`)
    captchaChallenge.value = res.data
    captchaCode.value = ''
  } finally {
    downloadCaptchaLoadingId.value = null
  }
}

async function submitResourceDownload() {
  if (!selectedDownloadResource.value || !captchaChallenge.value) return
  resourceDownloadSubmitting.value = true
  try {
    const res = await api.post<UrlCheckResult>(`/standard-resources/${selectedDownloadResource.value.id}/download-with-captcha`, {
      challenge_id: captchaChallenge.value.challenge_id,
      verify_code: captchaCode.value,
    })
    ElMessage.success(res.data.message || '真实文件已入库')
    showResourceDownloadDialog.value = false
    await loadStandardSearch()
  } finally {
    resourceDownloadSubmitting.value = false
  }
}

onMounted(loadStandardSearch)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>候选记录池</h2>
      <el-button :icon="Refresh" @click="resetStandardSearch">刷新</el-button>
    </div>
    <el-alert title="这里搜索的是本地已入库的官方标准元数据；真实文件下载需要人工输入官方下载页验证码。" type="info" :closable="false" class="inline-alert" />
    <el-form :inline="true" class="filters">
      <el-form-item label="标准">
        <el-input v-model="standardSearchQuery.q" clearable placeholder="标准号、名称、关键词" style="width: 360px" @keyup.enter="resetStandardSearch" />
      </el-form-item>
      <el-form-item label="状态">
        <el-select v-model="standardSearchQuery.source_status" clearable style="width: 140px">
          <el-option label="现行" value="现行" />
          <el-option label="即将实施" value="即将实施" />
          <el-option label="废止" value="废止" />
        </el-select>
      </el-form-item>
      <el-form-item><el-button type="primary" :icon="Search" @click="resetStandardSearch">搜索</el-button></el-form-item>
    </el-form>
    <el-table :data="standardSearchResources" :height="standardSearchTableHeight" @row-click="onRowClick">
      <el-table-column prop="standard_no" label="标准号" width="170" />
      <el-table-column prop="standard_name" label="名称" min-width="320" show-overflow-tooltip />
      <el-table-column prop="source_status" label="官方状态" width="120" />
      <el-table-column prop="resource_type" label="类型" width="120" />
      <el-table-column prop="publish_date" label="发布日期" width="120" :formatter="dateFormatter" />
      <el-table-column prop="effective_date" label="实施日期" width="120" :formatter="dateFormatter" />
      <el-table-column label="本地文件" width="100">
        <template #default="{ row }">
          <el-tag :type="row.matched_document_count ? 'success' : 'info'">{{ row.matched_document_count ? '有' : '无' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="官方全文" width="110">
        <template #default="{ row }">
          <el-tag :type="row.pdf_trial_url ? 'success' : 'info'">{{ row.pdf_trial_url ? '有入口' : '无入口' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" :disabled="!row.pdf_trial_url" :loading="downloadCaptchaLoadingId === row.id" @click.stop="openResourceDownload(row)">下载文件</el-button>
        </template>
      </el-table-column>
    </el-table>
    <CursorPager
      :pager="standardSearchPager"
      :total="standardSearchTotal"
      :page-size-options="pageSizeOptions"
      @prev="prevCursorPage(standardSearchPager, loadStandardSearch)"
      @next="nextCursorPage(standardSearchPager, loadStandardSearch)"
      @page-size-change="(size) => { standardSearchQuery.page_size = size; resetStandardSearch() }"
    />
  </section>

  <el-dialog v-model="showResourceDownloadDialog" title="人工验证码下载真实文件" width="520px">
    <div v-if="selectedDownloadResource" class="captcha-download">
      <p class="captcha-title">{{ selectedDownloadResource.standard_no || '-' }} {{ selectedDownloadResource.standard_name }}</p>
      <el-alert title="验证码由官方下载页生成，仅用于本次真实 PDF 下载；非 PDF 响应不会写入文件库。" type="info" :closable="false" />
      <div v-if="captchaChallenge" class="captcha-row">
        <img class="captcha-image" :src="captchaImageSrc()" alt="验证码" @click="refreshResourceCaptcha" />
        <el-button :loading="downloadCaptchaLoadingId === selectedDownloadResource.id" @click="refreshResourceCaptcha">换一张</el-button>
      </div>
      <el-input v-model="captchaCode" maxlength="8" placeholder="输入验证码" @keyup.enter="submitResourceDownload" />
    </div>
    <template #footer>
      <el-button @click="showResourceDownloadDialog = false">取消</el-button>
      <el-button :loading="resourceDownloadSubmitting" @click="refreshResourceCaptcha">刷新验证码</el-button>
      <el-button type="primary" :loading="resourceDownloadSubmitting" :disabled="!captchaChallenge || !captchaCode" @click="submitResourceDownload">下载并入库</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.inline-alert {
  margin-bottom: 14px;
}
.captcha-download {
  display: grid;
  gap: 14px;
}
.captcha-title {
  margin: 0;
  font-weight: 600;
}
.captcha-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.captcha-image {
  width: 132px;
  height: 44px;
  object-fit: contain;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  cursor: pointer;
}
</style>
