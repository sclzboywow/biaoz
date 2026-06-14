<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Plus, Search } from '@element-plus/icons-vue'
import { api, type DocumentItem, type Page } from '../../api'
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
import { manualStatusFormatter, sourceStatusFormatter, systemStatusFormatter } from '../../utils/tableFormatters'

const { openEvidence } = useObjectNavigation()

const documents = ref<DocumentItem[]>([])
const documentTotal = ref(0)
const showDocumentDialog = ref(false)
const pagedTableHeight = 'calc(100vh - 260px)'
const pageSizeOptions = [20, 50, 100, 200]

const documentQuery = reactive({
  page: 1,
  page_size: 50,
  q: '',
  source_status: '',
  system_status: '',
  manual_status: '',
  valid_status: '',
  review_status: '',
  metadata_status: '',
  classification_decision: '',
  classification_risk_level: '',
  doc_type: '',
})
const documentPager = createCursorPager()
const documentForm = reactive({ title: '', standard_no: '', category: '', issuing_authority: '' })

async function loadDocuments() {
  const res = await api.get<Page<DocumentItem>>('/documents/page', { params: pageParams(documentQuery, documentPager) })
  documents.value = res.data.items
  documentTotal.value = res.data.total
  applyPageResultWithQuery(documentQuery, documentPager, res.data)
}

async function resetDocuments() {
  resetCursorPager(documentPager)
  await loadDocuments()
}

async function createDocument() {
  await api.post('/documents', documentForm)
  showDocumentDialog.value = false
  Object.assign(documentForm, { title: '', standard_no: '', category: '', issuing_authority: '' })
  await loadDocuments()
}

function openDocument(row: DocumentItem) {
  openEvidence(undefined, row.id)
}

onMounted(loadDocuments)
</script>

<template>
  <section class="panel">
    <div class="toolbar">
      <h2>文件归档库</h2>
      <el-button type="primary" :icon="Plus" @click="showDocumentDialog = true">新增</el-button>
    </div>
    <el-form :inline="true" class="filters">
      <el-form-item label="查询"><el-input v-model="documentQuery.q" clearable placeholder="标题、编号、分类、发布单位" @keyup.enter="resetDocuments" /></el-form-item>
      <el-form-item label="来源状态">
        <el-select v-model="documentQuery.source_status" clearable style="width: 140px">
          <el-option label="现行" value="现行" />
          <el-option label="废止" value="废止" />
          <el-option label="被替代" value="被替代" />
          <el-option label="即将实施" value="即将实施" />
          <el-option label="未知" value="未知" />
        </el-select>
      </el-form-item>
      <el-form-item label="系统判断">
        <el-select v-model="documentQuery.system_status" clearable style="width: 150px">
          <el-option label="来源确认现行" value="来源确认现行" />
          <el-option label="来源确认废止" value="来源确认废止" />
          <el-option label="疑似被替代" value="疑似被替代" />
          <el-option label="多来源冲突" value="多来源冲突" />
          <el-option label="待复核" value="待复核" />
        </el-select>
      </el-form-item>
      <el-form-item label="复核状态">
        <el-select v-model="documentQuery.review_status" clearable style="width: 140px">
          <el-option label="自动确认" value="自动确认" />
          <el-option label="自动分类" value="自动分类" />
          <el-option label="风险隔离" value="风险隔离" />
          <el-option label="冲突拦截" value="冲突拦截" />
          <el-option label="待复核" value="待复核" />
        </el-select>
      </el-form-item>
      <el-form-item label="有效状态">
        <el-select v-model="documentQuery.valid_status" clearable style="width: 150px">
          <el-option label="来源确认现行" value="来源确认现行" />
          <el-option label="来源确认废止" value="来源确认废止" />
          <el-option label="疑似被替代" value="疑似被替代" />
          <el-option label="系统推定未知" value="系统推定未知" />
          <el-option label="隔离留存" value="隔离留存" />
          <el-option label="冲突拦截" value="冲突拦截" />
        </el-select>
      </el-form-item>
      <el-form-item label="元数据状态">
        <el-select v-model="documentQuery.metadata_status" clearable style="width: 150px">
          <el-option label="系统自动确认" value="系统自动确认" />
          <el-option label="系统自动分类" value="系统自动分类" />
          <el-option label="系统隔离" value="系统隔离" />
          <el-option label="系统冲突拦截" value="系统冲突拦截" />
        </el-select>
      </el-form-item>
      <el-form-item label="自动决策">
        <el-select v-model="documentQuery.classification_decision" clearable style="width: 140px">
          <el-option label="自动确认" value="auto_confirm" />
          <el-option label="自动分类" value="auto_classify" />
          <el-option label="风险隔离" value="quarantine" />
          <el-option label="冲突拦截" value="conflict_block" />
        </el-select>
      </el-form-item>
      <el-form-item label="风险等级">
        <el-select v-model="documentQuery.classification_risk_level" clearable style="width: 110px">
          <el-option label="低" value="low" />
          <el-option label="中" value="medium" />
          <el-option label="高" value="high" />
        </el-select>
      </el-form-item>
      <el-form-item><el-button :icon="Search" @click="resetDocuments">查询</el-button></el-form-item>
    </el-form>
    <el-table :data="documents" :height="pagedTableHeight" @row-click="openDocument">
      <el-table-column prop="title" label="文件标题" min-width="280" show-overflow-tooltip />
      <el-table-column prop="standard_no" label="标准编号" width="150" />
      <el-table-column prop="doc_type" label="类型" width="90" />
      <el-table-column prop="category" label="分类" width="130" />
      <el-table-column prop="standard_level" label="标准层级" width="110" />
      <el-table-column prop="classification_confidence_score" label="置信度" width="90" />
      <el-table-column prop="classification_risk_level" label="风险" width="80" />
      <el-table-column prop="classification_decision" label="自动决策" width="110" />
      <el-table-column prop="classification_reason" label="分类依据" min-width="180" show-overflow-tooltip />
      <el-table-column prop="source_status" label="来源状态" width="120" :formatter="sourceStatusFormatter" />
      <el-table-column prop="system_status" label="系统判断" width="140" :formatter="systemStatusFormatter" show-overflow-tooltip />
      <el-table-column prop="manual_status" label="人工复核" width="120" :formatter="manualStatusFormatter" />
      <el-table-column prop="metadata_status" label="元数据" width="120" />
    </el-table>
    <CursorPager
      :pager="documentPager"
      :total="documentTotal"
      :page-size-options="pageSizeOptions"
      @prev="prevCursorPage(documentPager, loadDocuments)"
      @next="nextCursorPage(documentPager, loadDocuments)"
      @page-size-change="(size) => { documentQuery.page_size = size; resetDocuments() }"
    />
  </section>

  <el-dialog v-model="showDocumentDialog" title="新增文件台账" width="640px">
    <el-form label-width="96px" :model="documentForm">
      <el-form-item label="文件标题"><el-input v-model="documentForm.title" /></el-form-item>
      <el-form-item label="标准编号"><el-input v-model="documentForm.standard_no" /></el-form-item>
      <el-form-item label="分类"><el-input v-model="documentForm.category" /></el-form-item>
      <el-form-item label="发布单位"><el-input v-model="documentForm.issuing_authority" /></el-form-item>
    </el-form>
    <template #footer><el-button @click="showDocumentDialog = false">取消</el-button><el-button type="primary" @click="createDocument">保存</el-button></template>
  </el-dialog>
</template>
