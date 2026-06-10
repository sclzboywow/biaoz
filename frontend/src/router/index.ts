import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('../layouts/MainLayout.vue'),
    redirect: '/dashboard/governance',
    children: [
      // 工作台
      { path: 'dashboard/overview', name: 'workbench-overview', component: () => import('../views/dashboard/WorkbenchOverviewView.vue'), meta: { title: '工作台总览', module: 'workbench' } },
      { path: 'dashboard/governance', name: 'governance-dashboard', component: () => import('../views/dashboard/GovernanceDashboardView.vue'), meta: { title: '治理总览', module: 'workbench' } },
      { path: 'dashboard/supervision', name: 'auto-supervision', component: () => import('../views/dashboard/AutoSupervisionCenterView.vue'), meta: { title: '自动监督中心', module: 'workbench' } },
      { path: 'dashboard/today-tasks', name: 'today-tasks', component: () => import('../views/dashboard/TodayTasksView.vue'), meta: { title: '今日任务', module: 'workbench' } },
      { path: 'dashboard/high-risk', name: 'high-risk', component: () => import('../views/dashboard/HighRiskExceptionsView.vue'), meta: { title: '高风险异常', module: 'workbench' } },

      // 来源治理
      { path: 'source-governance/sources', name: 'source-master', component: () => import('../views/source-governance/SourceMasterView.vue'), meta: { title: '来源主档', module: 'source-governance' } },
      { path: 'source-governance/sources/:id', name: 'source-master-detail', component: () => import('../views/source-governance/SourceMasterDetailView.vue'), meta: { title: '来源主档详情', module: 'source-governance' } },
      { path: 'source-governance/url-sources', name: 'url-governance', component: () => import('../views/source-governance/UrlSourceGovernanceView.vue'), meta: { title: 'URL 来源治理', module: 'source-governance' } },
      { path: 'source-governance/raw-records', name: 'raw-records', component: () => import('../views/source-governance/RawRecordsView.vue'), meta: { title: '原始记录池', module: 'source-governance' } },
      { path: 'source-governance/candidates', name: 'candidate-pool', component: () => import('../views/source-governance/CandidatePoolView.vue'), meta: { title: '候选记录池', module: 'source-governance' } },
      { path: 'source-governance/health', name: 'source-health', component: () => import('../views/source-governance/SourceHealthView.vue'), meta: { title: '来源健康度', module: 'source-governance' } },
      { path: 'source-governance/blacklist', name: 'blacklist-sources', component: () => import('../views/source-governance/BlacklistSourcesView.vue'), meta: { title: '黑名单/低可信来源', module: 'source-governance' } },

      // 采集归档
      { path: 'collection/tasks', name: 'collection-tasks', component: () => import('../views/collection/CollectionTasksView.vue'), meta: { title: '文件采集任务', module: 'collection' } },
      { path: 'collection/ocr-queue', name: 'ocr-queue', component: () => import('../views/collection/OcrDownloadQueueView.vue'), meta: { title: 'OCR 下载队列', module: 'collection' } },
      { path: 'collection/file-objects', name: 'file-objects', component: () => import('../views/collection/FileObjectLibraryView.vue'), meta: { title: '文件对象库', module: 'collection' } },
      { path: 'collection/archive', name: 'file-archive', component: () => import('../views/collection/DocumentArchiveView.vue'), meta: { title: '文件归档库', module: 'collection' } },
      { path: 'collection/versions', name: 'versions', component: () => import('../views/collection/VersionsView.vue'), meta: { title: '版本管理', module: 'collection' } },

      // 标准主库
      { path: 'standards/resources', name: 'standard-resources', component: () => import('../views/standards/StandardResourcesView.vue'), meta: { title: '标准资源主库', module: 'standards' } },
      { path: 'standards/file-matches', name: 'file-matches', component: () => import('../views/standards/FileMatchesView.vue'), meta: { title: '本地文件匹配', module: 'standards' } },
      { path: 'standards/evidence', name: 'evidence-explorer', component: () => import('../views/standards/EvidenceExplorerView.vue'), meta: { title: '证据链', module: 'standards' } },
      { path: 'standards/relations', name: 'relations-explorer', component: () => import('../views/standards/RelationsExplorerView.vue'), meta: { title: '替代关系', module: 'standards' } },
      { path: 'standards/:id', name: 'standard-detail', component: () => import('../views/standards/StandardDetailView.vue'), meta: { title: '标准详情', module: 'standards' } },

      // 状态异常
      { path: 'exceptions/status-sync', name: 'status-sync', component: () => import('../views/exceptions/StatusSyncView.vue'), meta: { title: '状态同步', module: 'exceptions' } },
      { path: 'exceptions/changes', name: 'source-changes', component: () => import('../views/exceptions/SourceChangesView.vue'), meta: { title: '变更监测', module: 'exceptions' } },
      { path: 'exceptions/alerts', name: 'alerts', component: () => import('../views/exceptions/AlertsView.vue'), meta: { title: '异常提醒', module: 'exceptions' } },
      { path: 'exceptions/pending', name: 'pending-exceptions', component: () => import('../views/exceptions/PendingExceptionsView.vue'), meta: { title: '待处理异常', module: 'exceptions' } },
      { path: 'exceptions/audit-logs', name: 'audit-logs', component: () => import('../views/exceptions/AuditLogsView.vue'), meta: { title: '流程审计日志', module: 'exceptions' } },

      // 系统配置
      { path: 'settings/general', name: 'settings-general', component: () => import('../views/settings/SettingsGeneralView.vue'), meta: { title: '系统设置', module: 'settings', permission: 'settings' } },
      { path: 'settings/source-rules', name: 'settings-source-rules', component: () => import('../views/settings/SettingsSectionView.vue'), meta: { title: '来源规则', module: 'settings', settingKeys: ['source_', 'trusted_', 'governance_'], permission: 'source-rules' } },
      { path: 'settings/ocr', name: 'settings-ocr', component: () => import('../views/settings/SettingsSectionView.vue'), meta: { title: 'OCR 配置', module: 'settings', settingKeys: ['ocr_'], permission: 'ocr-config' } },
      { path: 'settings/field-mapping', name: 'settings-field-mapping', component: () => import('../views/settings/SettingsSectionView.vue'), meta: { title: '字段映射', module: 'settings', settingKeys: ['field_', 'mapping_'], permission: 'field-mapping' } },
      { path: 'settings/rate-limit', name: 'settings-rate-limit', component: () => import('../views/settings/SettingsSectionView.vue'), meta: { title: '采集限速', module: 'settings', settingKeys: ['rate_', 'collect_', 'ingest_'], permission: 'rate-limit' } },
      { path: 'settings/storage', name: 'settings-storage', component: () => import('../views/settings/SettingsSectionView.vue'), meta: { title: '存储配置', module: 'settings', settingKeys: ['storage_'], permission: 'storage-config' } },

      // 旧版入口（兼容）
      { path: 'legacy/overview', name: 'legacy-overview', component: () => import('../views/dashboard/WorkbenchOverviewView.vue'), meta: { title: '旧版总览', legacy: true } },
      { path: 'legacy/review', name: 'legacy-review', redirect: '/exceptions/pending' },
    ],
  },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router
