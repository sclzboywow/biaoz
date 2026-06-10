<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api, type ResourceChain } from '../../api'
import { useObjectNavigation } from '../../composables/useObjectNavigation'
import {
  formatDate,
  formatDateTime,
  jsonPretty,
  officialFieldEntries,
  officialLinkEntries,
  officialLinkLabel,
  openExternalUrl,
} from '../../utils/officialFields'
import { dateTimeFormatter, manualStatusFormatter, sourceStatusFormatter, systemStatusFormatter } from '../../utils/tableFormatters'

const route = useRoute()
const router = useRouter()
const { openEvidence, openAudit, openDecision } = useObjectNavigation()

const chain = ref<ResourceChain | null>(null)
const loading = ref(false)
const showRawResourceDetail = ref(false)
const activeTab = ref('basic')

const resourceId = computed(() => Number(route.params.id))

watch(
  () => route.query.tab,
  (tab) => {
    if (typeof tab === 'string' && tab) activeTab.value = tab
  },
  { immediate: true },
)

watch(activeTab, (tab) => {
  router.replace({ query: { ...route.query, tab } })
})

async function loadChain() {
  if (!resourceId.value) return
  loading.value = true
  try {
    const res = await api.get<ResourceChain>(`/standard-resources/${resourceId.value}/chain`)
    chain.value = res.data
  } finally {
    loading.value = false
  }
}

async function confirmRelation(id: number) {
  await api.patch(`/standard-relations/${id}`, { is_manual_confirmed: true })
  ElMessage.success('替代/相关关系已确认')
  await loadChain()
}

function openDocumentEvidence(documentId: number) {
  openEvidence(undefined, documentId)
}

onMounted(loadChain)
</script>

<template>
  <section v-loading="loading" class="panel chain-detail-page">
    <div class="toolbar">
      <h2 v-if="chain">{{ chain.resource.standard_no || '' }} {{ chain.resource.standard_name }}</h2>
      <h2 v-else>标准详情</h2>
      <el-button :icon="Refresh" @click="loadChain">刷新</el-button>
    </div>

    <el-alert v-if="chain?.processing_advice" :title="chain.processing_advice" type="warning" :closable="false" class="chain-advice" />

    <el-tabs v-if="chain" v-model="activeTab" class="content-tabs">
      <el-tab-pane label="基本信息" name="basic">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="标准编号">{{ chain.resource.standard_no }}</el-descriptions-item>
          <el-descriptions-item label="规范编号">{{ chain.resource.normalized_standard_no }}</el-descriptions-item>
          <el-descriptions-item label="标准名称" :span="2">{{ chain.resource.standard_name }}</el-descriptions-item>
          <el-descriptions-item label="资源类型">{{ chain.resource.resource_type }}</el-descriptions-item>
          <el-descriptions-item label="来源状态">{{ chain.resource.source_status }}</el-descriptions-item>
          <el-descriptions-item label="系统判断">{{ chain.resource.system_status }}</el-descriptions-item>
          <el-descriptions-item label="人工复核">{{ chain.resource.manual_status || '-' }}</el-descriptions-item>
          <el-descriptions-item label="发布日期">{{ formatDate(chain.resource.publish_date) }}</el-descriptions-item>
          <el-descriptions-item label="实施日期">{{ formatDate(chain.resource.effective_date) }}</el-descriptions-item>
          <el-descriptions-item label="废止日期">{{ formatDate(chain.resource.abolish_date) }}</el-descriptions-item>
          <el-descriptions-item label="来源详情页">
            <el-button v-if="chain.resource.detail_url" link type="primary" @click="openExternalUrl(chain.resource.detail_url)">打开来源详情</el-button>
            <span v-else>-</span>
          </el-descriptions-item>
        </el-descriptions>

        <template v-if="chain.details.length">
          <h3 class="section-title">官方信息</h3>
          <el-descriptions :column="1" border>
            <el-descriptions-item v-for="item in officialFieldEntries(chain.details[0].catalog_text)" :key="item.key" :label="item.label" :span="item.span">
              {{ item.value || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="官方入口">
              <div v-if="officialLinkEntries(chain.details[0].catalog_text).length" class="official-link-actions">
                <el-button v-for="[label, url] in officialLinkEntries(chain.details[0].catalog_text)" :key="label" size="small" @click="openExternalUrl(url)">
                  {{ officialLinkLabel(label) }}
                </el-button>
              </div>
              <span v-else>-</span>
            </el-descriptions-item>
            <el-descriptions-item label="采集时间">{{ formatDateTime(chain.details[0].captured_at) }}</el-descriptions-item>
          </el-descriptions>
          <div class="raw-detail-toggle">
            <el-button size="small" @click="showRawResourceDetail = !showRawResourceDetail">
              {{ showRawResourceDetail ? '收起原始官方数据' : '查看原始官方数据（排查用）' }}
            </el-button>
          </div>
          <el-tabs v-if="showRawResourceDetail" class="detail-json-tabs">
            <el-tab-pane label="详情 JSON"><pre class="json-block">{{ jsonPretty(chain.details[0].product_info) }}</pre></el-tab-pane>
            <el-tab-pane label="替代关系"><pre class="json-block">{{ jsonPretty(chain.details[0].change_info) }}</pre></el-tab-pane>
            <el-tab-pane label="相关标准"><pre class="json-block">{{ jsonPretty(chain.details[0].related_books) }}</pre></el-tab-pane>
          </el-tabs>
        </template>
      </el-tab-pane>

      <el-tab-pane label="证据" name="evidence">
        <el-table :data="chain.evidences" height="calc(100vh - 280px)">
          <el-table-column prop="source_name" label="来源网站" width="160" />
          <el-table-column prop="source_level" label="等级" width="80" />
          <el-table-column prop="raw_status_text" label="原始状态" width="120" />
          <el-table-column prop="parsed_status" label="解析结果" width="140" />
          <el-table-column prop="evidence_note" label="证据说明" min-width="360" show-overflow-tooltip />
          <el-table-column prop="source_url" label="原始 URL" min-width="280" show-overflow-tooltip />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="文件" name="files">
        <el-table :data="chain.documents" height="calc(100vh - 280px)">
          <el-table-column prop="standard_no" label="编号" width="150" />
          <el-table-column prop="title" label="文件名称" min-width="320" show-overflow-tooltip />
          <el-table-column prop="source_status" label="来源状态" width="120" :formatter="sourceStatusFormatter" />
          <el-table-column prop="system_status" label="系统判断" width="140" :formatter="systemStatusFormatter" show-overflow-tooltip />
          <el-table-column prop="manual_status" label="人工复核" width="120" :formatter="manualStatusFormatter" />
          <el-table-column label="操作" width="110">
            <template #default="{ row }"><el-button size="small" @click.stop="openDocumentEvidence(row.id)">证据链</el-button></template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="版本" name="versions">
        <el-table :data="chain.versions" height="calc(100vh - 280px)">
          <el-table-column prop="version_no" label="版本" width="90" />
          <el-table-column prop="file_name" label="文件名" min-width="280" show-overflow-tooltip />
          <el-table-column prop="change_type" label="变化" width="100" />
          <el-table-column prop="is_current" label="当前" width="90" />
          <el-table-column prop="file_hash" label="文件哈希" min-width="240" show-overflow-tooltip />
          <el-table-column prop="downloaded_at" label="下载时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="关系" name="relations">
        <el-table :data="chain.relations" height="calc(100vh - 280px)">
          <el-table-column prop="current_standard_no" label="当前标准" width="160" />
          <el-table-column prop="related_standard_no" label="关联标准" width="160" />
          <el-table-column prop="relation_type" label="关系类型" width="120" />
          <el-table-column prop="relation_text" label="关系原文" min-width="360" show-overflow-tooltip />
          <el-table-column prop="is_manual_confirmed" label="人工确认" width="100" />
          <el-table-column label="操作" width="110">
            <template #default="{ row }">
              <el-button size="small" :disabled="row.is_manual_confirmed" @click="confirmRelation(row.id)">确认关系</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="决策" name="decision">
        <el-descriptions v-if="chain.resource" :column="1" border>
          <el-descriptions-item label="自动决策">{{ chain.resource.auto_decision || '-' }}</el-descriptions-item>
          <el-descriptions-item label="置信度">{{ chain.resource.confidence_score ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="决策原因">{{ chain.resource.decision_reason || '-' }}</el-descriptions-item>
          <el-descriptions-item label="风险等级">{{ chain.resource.risk_level || '-' }}</el-descriptions-item>
          <el-descriptions-item label="最近治理">{{ formatDateTime(chain.resource.last_governed_at) }}</el-descriptions-item>
        </el-descriptions>
        <el-button style="margin-top: 12px" @click="openDecision(chain.resource.id)">查看决策详情</el-button>
      </el-tab-pane>

      <el-tab-pane label="审计" name="audit">
        <el-button type="primary" @click="openAudit('standard_resource', chain.resource.id, 'GOVERNANCE_DECISION')">打开流程审计日志</el-button>
      </el-tab-pane>

      <el-tab-pane label="提醒" name="alerts">
        <el-table :data="chain.alerts" height="calc(100vh - 280px)">
          <el-table-column prop="alert_level" label="等级" width="90" />
          <el-table-column prop="alert_type" label="类型" width="140" />
          <el-table-column prop="message" label="消息" min-width="360" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="110" />
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<style scoped>
.section-title {
  margin: 16px 0 8px;
}
.official-link-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.raw-detail-toggle {
  margin-top: 12px;
}
.json-block {
  max-height: 360px;
  overflow: auto;
  padding: 12px;
  background: #f7f8fa;
  border-radius: 6px;
  font-size: 12px;
}
</style>
