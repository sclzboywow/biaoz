<template>
  <el-container class="app-shell">
    <el-aside width="248px" class="sidebar">
      <div class="brand">标准规范文件动态管理系统</div>
      <el-menu :default-active="activeView" background-color="#17202a" text-color="#d5dde5" active-text-color="#ffffff" @select="switchView">
        <el-menu-item index="dashboard"><el-icon><DataBoard /></el-icon><span>总览</span></el-menu-item>
        <el-menu-item index="urlSources"><el-icon><Link /></el-icon><span>URL 来源管理</span></el-menu-item>
        <el-menu-item index="collection"><el-icon><Download /></el-icon><span>文件采集管理</span></el-menu-item>
        <el-menu-item index="documents"><el-icon><Document /></el-icon><span>文件库管理</span></el-menu-item>
        <el-menu-item index="versions"><el-icon><Files /></el-icon><span>版本管理</span></el-menu-item>
        <el-menu-item index="review"><el-icon><CircleCheck /></el-icon><span>状态复核</span></el-menu-item>
        <el-menu-item index="alerts"><el-icon><Bell /></el-icon><span>更新提醒</span></el-menu-item>
        <el-menu-item index="trustedResources"><el-icon><Medal /></el-icon><span>可信源资源库</span></el-menu-item>
        <el-menu-item index="fileMatches"><el-icon><Aim /></el-icon><span>本地文件匹配</span></el-menu-item>
        <el-menu-item index="statusSyncLogs"><el-icon><Switch /></el-icon><span>状态同步记录</span></el-menu-item>
        <el-menu-item index="sourceChanges"><el-icon><Warning /></el-icon><span>变更监测</span></el-menu-item>
        <el-menu-item index="settings"><el-icon><Setting /></el-icon><span>系统设置</span></el-menu-item>
      </el-menu>
    </el-aside>

    <el-main class="main">
      <section v-if="activeView === 'dashboard'">
        <div class="status-row">
          <div class="metric">URL 来源<strong>{{ urlTotal }}</strong></div>
          <div class="metric">文件库<strong>{{ documentTotal }}</strong></div>
          <div class="metric">待复核<strong>{{ pendingReviewCount }}</strong></div>
          <div class="metric">未处理提醒<strong>{{ pendingAlertCount }}</strong></div>
        </div>
        <div class="panel">
          <div class="toolbar">
            <h2>最近提醒</h2>
            <el-button :icon="Refresh" @click="loadAll">刷新</el-button>
          </div>
          <el-table :data="alerts" :height="dashboardTableHeight">
            <el-table-column prop="alert_level" label="等级" width="90" />
            <el-table-column prop="alert_type" label="类型" width="140" />
            <el-table-column prop="message" label="消息" />
            <el-table-column prop="status" label="状态" width="110" />
            <el-table-column label="链路" width="110">
              <template #default="{ row }">
                <el-button size="small" :disabled="!row.document_id" @click.stop="openDocumentChainById(row.document_id)">文件链路</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination layout="total, sizes, prev, pager, next" :total="alertTotal" v-model:current-page="alertQuery.page" v-model:page-size="alertQuery.page_size" :page-sizes="[20, 50, 100, 200]" @change="loadAlerts" />
        </div>
      </section>

      <section v-if="activeView === 'urlSources'" class="panel">
        <div class="toolbar">
          <h2>URL 来源管理</h2>
          <div>
            <el-button :icon="Refresh" :loading="checkingAll" @click="checkAllSources">检查非手动 URL</el-button>
            <el-button type="primary" :icon="Plus" @click="showUrlDialog = true">新增</el-button>
          </div>
        </div>
        <el-form :inline="true" class="filters">
          <el-form-item label="查询"><el-input v-model="urlQuery.q" clearable placeholder="名称、URL、备注" @keyup.enter="loadUrlSources" /></el-form-item>
          <el-form-item label="状态">
            <el-select v-model="urlQuery.status" clearable style="width: 120px"><el-option label="正常" value="正常" /><el-option label="失效" value="失效" /><el-option label="异常" value="异常" /><el-option label="需登录" value="需登录" /></el-select>
          </el-form-item>
          <el-form-item label="频率">
            <el-select v-model="urlQuery.check_frequency" clearable style="width: 130px"><el-option label="manual" value="manual" /><el-option label="daily" value="daily" /><el-option label="weekly" value="weekly" /><el-option label="monthly" value="monthly" /></el-select>
          </el-form-item>
          <el-form-item><el-button :icon="Search" @click="loadUrlSources">查询</el-button></el-form-item>
        </el-form>
        <el-table :data="urlSources" :height="pagedTableHeight">
          <el-table-column prop="source_name" label="来源名称" width="240" show-overflow-tooltip />
          <el-table-column prop="url" label="URL" min-width="360" show-overflow-tooltip />
          <el-table-column prop="source_type" label="类型" width="120" />
          <el-table-column prop="category" label="分类" width="120" />
          <el-table-column prop="check_frequency" label="频率" width="100" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column prop="last_checked_at" label="最后检查" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }"><el-button size="small" :loading="checkingSourceId === row.id" @click="checkSource(row.id)">检查</el-button></template>
          </el-table-column>
        </el-table>
        <el-pagination layout="total, sizes, prev, pager, next" :total="urlTotal" v-model:current-page="urlQuery.page" v-model:page-size="urlQuery.page_size" :page-sizes="[20, 50, 100, 200]" @change="loadUrlSources" />
      </section>

      <section v-if="activeView === 'collection'" class="panel">
        <div class="toolbar">
          <h2>文件采集管理</h2>
          <div>
            <el-button :icon="Refresh" @click="loadCollectionTasks">刷新任务</el-button>
            <el-button type="primary" :loading="checkingAll" @click="createUrlCheckTask">创建后台检查任务</el-button>
          </div>
        </div>
        <el-tabs v-model="collectionActiveTab" class="content-tabs">
          <el-tab-pane label="采集来源" name="sources">
            <el-alert title="已导入的大批量 URL 默认是 manual，不会被后台自动下载。需要采集时可在 URL 来源管理中单条检查，或后续按分类/批次放开频率。" type="info" :closable="false" />
            <el-table :data="urlSources" :height="collectionTableHeight" style="margin-top: 14px">
              <el-table-column prop="source_name" label="来源名称" min-width="260" show-overflow-tooltip />
              <el-table-column prop="status" label="链接状态" width="110" />
              <el-table-column prop="error_message" label="异常信息" min-width="260" show-overflow-tooltip />
              <el-table-column prop="last_checked_at" label="最后检查" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
              <el-table-column label="操作" width="120">
                <template #default="{ row }"><el-button size="small" @click="checkSource(row.id)">采集</el-button></template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="后台任务进度" name="tasks">
            <el-table :data="collectionTasks" :height="collectionTableHeight">
              <el-table-column prop="id" label="任务ID" width="90" />
              <el-table-column prop="task_type" label="任务类型" width="120" />
              <el-table-column prop="status" label="状态" width="110" />
              <el-table-column label="进度" width="220">
                <template #default="{ row }">
                  <el-progress :percentage="taskPercent(row)" :text-inside="true" :stroke-width="18" />
                </template>
              </el-table-column>
              <el-table-column prop="success" label="成功" width="90" />
              <el-table-column prop="failed" label="失败" width="90" />
              <el-table-column prop="last_source_id" label="游标" width="100" />
              <el-table-column prop="heartbeat_at" label="心跳时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
              <el-table-column prop="message" label="说明" min-width="260" show-overflow-tooltip />
              <el-table-column prop="started_at" label="开始时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
              <el-table-column prop="finished_at" label="完成时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
              <el-table-column label="操作" width="110" fixed="right">
                <template #default="{ row }">
                  <el-button
                    size="small"
                    :disabled="row.status === 'finished' || row.status === 'running'"
                    @click="resumeCollectionTask(row.id)"
                  >
                    继续
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </section>

      <section v-if="activeView === 'documents'" class="panel">
        <div class="toolbar">
          <h2>文件库管理</h2>
          <el-button type="primary" :icon="Plus" @click="showDocumentDialog = true">新增</el-button>
        </div>
        <el-form :inline="true" class="filters">
          <el-form-item label="查询"><el-input v-model="documentQuery.q" clearable placeholder="标题、编号、分类、发布单位" @keyup.enter="loadDocuments" /></el-form-item>
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
          <el-form-item label="人工复核">
            <el-select v-model="documentQuery.manual_status" clearable style="width: 140px">
              <el-option label="确认现行" value="确认现行" />
              <el-option label="确认废止" value="确认废止" />
              <el-option label="仅供参考" value="仅供参考" />
              <el-option label="暂不处理" value="暂不处理" />
            </el-select>
          </el-form-item>
          <el-form-item><el-button :icon="Search" @click="loadDocuments">查询</el-button></el-form-item>
        </el-form>
        <el-table :data="documents" :height="pagedTableHeight" @row-click="openDocumentChain">
          <el-table-column prop="title" label="文件标题" min-width="280" show-overflow-tooltip />
          <el-table-column prop="standard_no" label="标准编号" width="150" />
          <el-table-column prop="doc_type" label="类型" width="90" />
          <el-table-column prop="category" label="分类" width="130" />
          <el-table-column prop="source_status" label="来源状态" width="120" />
          <el-table-column prop="system_status" label="系统判断" width="140" />
          <el-table-column prop="manual_status" label="人工复核" width="120" />
          <el-table-column prop="metadata_status" label="元数据" width="120" />
        </el-table>
        <el-pagination layout="total, sizes, prev, pager, next" :total="documentTotal" v-model:current-page="documentQuery.page" v-model:page-size="documentQuery.page_size" :page-sizes="[20, 50, 100, 200]" @change="loadDocuments" />
      </section>

      <section v-if="activeView === 'versions'" class="panel">
        <div class="toolbar">
          <h2>版本管理</h2>
          <el-select v-model="selectedDocumentId" filterable placeholder="选择文件" style="width: 420px" @change="loadVersions">
            <el-option v-for="item in documents" :key="item.id" :label="item.title" :value="item.id" />
          </el-select>
        </div>
        <el-table :data="versions" :height="plainTableHeight">
          <el-table-column prop="version_no" label="版本" width="90" />
          <el-table-column prop="file_name" label="文件名" min-width="280" show-overflow-tooltip />
          <el-table-column prop="change_type" label="变化" width="100" />
          <el-table-column prop="is_current" label="当前" width="90" />
          <el-table-column prop="file_size" label="大小" width="110" />
          <el-table-column prop="file_hash" label="SHA-256" min-width="240" show-overflow-tooltip />
          <el-table-column prop="downloaded_at" label="下载时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
        </el-table>
      </section>

      <section v-if="activeView === 'review'" class="panel">
        <div class="toolbar">
          <h2>状态复核</h2>
          <el-button :icon="Search" @click="loadPendingReview">待复核</el-button>
        </div>
        <el-table :data="reviewDocuments" :height="plainTableHeight">
          <el-table-column prop="title" label="文件标题" min-width="280" show-overflow-tooltip />
          <el-table-column prop="standard_no" label="标准编号" width="150" />
          <el-table-column prop="source_status" label="来源状态" width="120" />
          <el-table-column prop="system_status" label="系统判断" width="140" />
          <el-table-column prop="manual_status" label="人工复核" width="120" />
          <el-table-column label="操作" width="310" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <el-button size="small" type="success" @click="reviewDocument(row.id, '确认现行')">确认现行</el-button>
                <el-button size="small" type="warning" @click="reviewDocument(row.id, '暂不处理')">暂不处理</el-button>
                <el-button size="small" type="danger" @click="reviewDocument(row.id, '确认废止')">确认废止</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section v-if="activeView === 'alerts'" class="panel">
        <div class="toolbar">
          <h2>更新提醒</h2>
          <el-button :icon="Refresh" @click="loadAlerts">刷新</el-button>
        </div>
        <el-form :inline="true" class="filters">
          <el-form-item label="查询"><el-input v-model="alertQuery.q" clearable placeholder="提醒内容" @keyup.enter="loadAlerts" /></el-form-item>
          <el-form-item label="状态"><el-select v-model="alertQuery.status" clearable style="width: 130px"><el-option label="未处理" value="未处理" /><el-option label="已处理" value="已处理" /><el-option label="忽略" value="忽略" /></el-select></el-form-item>
          <el-form-item><el-button :icon="Search" @click="loadAlerts">查询</el-button></el-form-item>
        </el-form>
        <el-table :data="alerts" :height="pagedTableHeight">
          <el-table-column prop="alert_level" label="等级" width="90" />
          <el-table-column prop="alert_type" label="类型" width="140" />
          <el-table-column prop="message" label="消息" min-width="320" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="110" />
          <el-table-column prop="created_at" label="创建时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
          <el-table-column label="操作" width="260" fixed="right">
            <template #default="{ row }">
              <el-button size="small" :disabled="!row.document_id" @click.stop="openDocumentChainById(row.document_id)">文件链路</el-button>
              <el-button size="small" type="success" :disabled="row.status !== '未处理'" @click="setAlertStatus(row.id, '已处理')">处理</el-button>
              <el-button size="small" :disabled="row.status !== '未处理'" @click="setAlertStatus(row.id, '忽略')">忽略</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination layout="total, sizes, prev, pager, next" :total="alertTotal" v-model:current-page="alertQuery.page" v-model:page-size="alertQuery.page_size" :page-sizes="[20, 50, 100, 200]" @change="loadAlerts" />
      </section>

      <section v-if="activeView === 'settings'" class="panel">
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
                @change="(value: boolean) => updateSetting(row.key, value ? 'true' : 'false')"
              />
              <el-input-number
                v-else-if="row.value_type === 'int'"
                :model-value="Number(row.value || 0)"
                :min="0"
                :step="60"
                controls-position="right"
                @change="(value: number | undefined) => updateSetting(row.key, String(value ?? 0))"
              />
              <el-input
                v-else-if="row.value_type === 'secret'"
                :model-value="row.value"
                type="password"
                show-password
                @change="(value: string) => updateSetting(row.key, value)"
              />
              <div v-else-if="row.key === 'storage_root'" class="setting-path-control">
                <el-input
                  :model-value="row.value"
                  @change="(value: string) => updateSetting(row.key, value)"
                />
                <el-button @click="chooseStorageRoot(row)">选择目录</el-button>
              </div>
              <el-input
                v-else
                :model-value="row.value"
                @change="(value: string) => updateSetting(row.key, value)"
              />
            </template>
          </el-table-column>
          <el-table-column prop="description" label="说明" min-width="320" show-overflow-tooltip />
          <el-table-column prop="updated_at" label="更新时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
        </el-table>
      </section>

      <section v-if="activeView === 'trustedResources'" class="panel">
        <div class="toolbar">
          <h2>可信源资源库</h2>
          <div>
            <el-select v-model="selectedTrustedSourceId" placeholder="选择可信源" style="width: 220px; margin-right: 8px" @change="loadTrustedResources">
              <el-option v-for="item in trustedSources" :key="item.id" :label="item.source_name" :value="item.id" />
            </el-select>
            <el-button :icon="Refresh" @click="loadTrustedResources">刷新</el-button>
            <el-button :loading="discoveringCategories" @click="discoverSourceCategories">发现分类</el-button>
            <el-button :loading="syncingPendingCategories" @click="syncPendingCategories">同步待同步分类</el-button>
            <el-button type="primary" :loading="syncingTrustedSource" @click="syncTrustedSource">同步当前源</el-button>
          </div>
        </div>
        <el-form :inline="true" class="filters">
          <el-form-item label="分类">
            <el-select v-model="selectedSourceCategoryId" clearable filterable placeholder="选择 sublibID" style="width: 360px">
              <el-option
                v-for="item in sourceCategories"
                :key="item.id"
                :label="`${item.source_category_id} ${item.category_path || item.category_name}`"
                :value="item.source_category_id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="查询"><el-input v-model="resourceQuery.q" clearable placeholder="编号、名称、关键词、分类" @keyup.enter="loadTrustedResources" /></el-form-item>
          <el-form-item label="状态"><el-select v-model="resourceQuery.source_status" clearable style="width: 120px"><el-option label="现行" value="现行" /><el-option label="废止" value="废止" /></el-select></el-form-item>
          <el-form-item><el-button :icon="Search" @click="loadTrustedResources">查询</el-button></el-form-item>
        </el-form>
        <el-tabs v-model="trustedResourceActiveTab" class="content-tabs">
          <el-tab-pane label="资源列表" name="resources">
            <el-table :data="trustedResources" :height="trustedResourceTableHeight" @row-click="openResourceChain">
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
            <el-pagination layout="total, sizes, prev, pager, next" :total="resourceTotal" v-model:current-page="resourceQuery.page" v-model:page-size="resourceQuery.page_size" :page-sizes="[20, 50, 100, 200]" @change="loadTrustedResources" />
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

      <section v-if="activeView === 'fileMatches'" class="panel">
        <div class="toolbar">
          <h2>本地文件匹配</h2>
          <el-button type="primary" :icon="Aim" @click="runFileMatch">按编号自动匹配</el-button>
        </div>
        <el-table :data="fileMatches" :height="plainTableHeight">
          <el-table-column prop="standard_resource_id" label="可信源资源" width="130" />
          <el-table-column prop="document_id" label="本地文件" width="110" />
          <el-table-column prop="match_type" label="匹配方式" width="160" />
          <el-table-column prop="match_score" label="分数" width="90" />
          <el-table-column prop="match_reason" label="原因" min-width="260" />
          <el-table-column prop="status" label="状态" width="120" />
          <el-table-column prop="matched_at" label="匹配时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
          <el-table-column label="链路" width="210" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click.stop="openDocumentChainById(row.document_id)">文件</el-button>
              <el-button size="small" @click.stop="openResourceChainById(row.standard_resource_id)">资源</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section v-if="activeView === 'statusSyncLogs'" class="panel">
        <div class="toolbar">
          <h2>状态同步记录</h2>
          <el-button :icon="Refresh" @click="loadStatusSyncLogs">刷新</el-button>
        </div>
        <el-table :data="statusSyncLogs" :height="plainTableHeight">
          <el-table-column prop="standard_resource_id" label="可信源资源" width="130" />
          <el-table-column prop="document_id" label="本地文件" width="110" />
          <el-table-column prop="old_status" label="原状态" width="140" />
          <el-table-column prop="new_status" label="新状态" width="140" />
          <el-table-column prop="sync_action" label="动作" width="150" />
          <el-table-column prop="sync_reason" label="原因/证据" min-width="360" show-overflow-tooltip />
          <el-table-column prop="synced_at" label="同步时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
          <el-table-column label="链路" width="210" fixed="right">
            <template #default="{ row }">
              <el-button size="small" :disabled="!row.document_id" @click.stop="openDocumentChainById(row.document_id)">文件</el-button>
              <el-button size="small" @click.stop="openResourceChainById(row.standard_resource_id)">资源</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section v-if="activeView === 'sourceChanges'" class="panel">
        <div class="toolbar">
          <h2>变更监测</h2>
          <el-button :icon="Refresh" @click="loadSourceChanges">刷新</el-button>
        </div>
        <el-table :data="sourceChanges" :height="plainTableHeight">
          <el-table-column prop="standard_resource_id" label="资源ID" width="110" />
          <el-table-column prop="document_id" label="本地文件" width="110" />
          <el-table-column prop="document_version_id" label="版本" width="90" />
          <el-table-column prop="field_name" label="字段" width="150" />
          <el-table-column prop="change_type" label="变化类型" width="130" />
          <el-table-column prop="old_value" label="旧值" min-width="220" show-overflow-tooltip />
          <el-table-column prop="new_value" label="新值" min-width="220" show-overflow-tooltip />
          <el-table-column prop="handled_status" label="处理状态" width="120" />
          <el-table-column prop="evidence_summary" label="证据链" min-width="280" show-overflow-tooltip />
          <el-table-column prop="detected_at" label="发现时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
          <el-table-column label="链路" width="210" fixed="right">
            <template #default="{ row }">
              <el-button size="small" :disabled="!row.document_id" @click.stop="openDocumentChainById(row.document_id)">文件</el-button>
              <el-button size="small" @click.stop="openResourceChainById(row.standard_resource_id)">资源</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </el-main>
  </el-container>

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

  <el-dialog v-model="showUrlDialog" title="新增 URL 来源" width="640px">
    <el-form label-width="96px" :model="urlForm">
      <el-form-item label="URL"><el-input v-model="urlForm.url" /></el-form-item>
      <el-form-item label="来源名称"><el-input v-model="urlForm.source_name" /></el-form-item>
      <el-form-item label="来源单位"><el-input v-model="urlForm.source_unit" /></el-form-item>
      <el-form-item label="来源类型"><el-select v-model="urlForm.source_type"><el-option label="文件直链" value="文件直链" /><el-option label="公告页面" value="公告页面" /><el-option label="目录页面" value="目录页面" /></el-select></el-form-item>
      <el-form-item label="检查频率"><el-select v-model="urlForm.check_frequency"><el-option label="manual" value="manual" /><el-option label="daily" value="daily" /><el-option label="weekly" value="weekly" /><el-option label="monthly" value="monthly" /></el-select></el-form-item>
      <el-form-item label="分类"><el-input v-model="urlForm.category" /></el-form-item>
    </el-form>
    <template #footer><el-button @click="showUrlDialog = false">取消</el-button><el-button type="primary" @click="createUrlSource">保存</el-button></template>
  </el-dialog>

  <el-dialog v-model="showDocumentDialog" title="新增文件台账" width="640px">
    <el-form label-width="96px" :model="documentForm">
      <el-form-item label="文件标题"><el-input v-model="documentForm.title" /></el-form-item>
      <el-form-item label="标准编号"><el-input v-model="documentForm.standard_no" /></el-form-item>
      <el-form-item label="分类"><el-input v-model="documentForm.category" /></el-form-item>
      <el-form-item label="发布单位"><el-input v-model="documentForm.issuing_authority" /></el-form-item>
    </el-form>
    <template #footer><el-button @click="showDocumentDialog = false">取消</el-button><el-button type="primary" @click="createDocument">保存</el-button></template>
  </el-dialog>

  <el-drawer v-model="chainDrawerVisible" :title="chainTitle" size="68%">
    <section v-if="resourceChain" class="chain-detail">
      <h3>可信源资源详情</h3>
      <el-alert v-if="resourceChain.processing_advice" :title="resourceChain.processing_advice" type="warning" :closable="false" class="chain-advice" />
      <el-descriptions :column="2" border>
        <el-descriptions-item label="标准编号">{{ resourceChain.resource.standard_no }}</el-descriptions-item>
        <el-descriptions-item label="规范编号">{{ resourceChain.resource.normalized_standard_no }}</el-descriptions-item>
        <el-descriptions-item label="标准名称">{{ resourceChain.resource.standard_name }}</el-descriptions-item>
        <el-descriptions-item label="资源类型">{{ resourceChain.resource.resource_type }}</el-descriptions-item>
        <el-descriptions-item label="来源状态">{{ resourceChain.resource.source_status }}</el-descriptions-item>
        <el-descriptions-item label="系统判断">{{ resourceChain.resource.system_status }}</el-descriptions-item>
        <el-descriptions-item label="人工复核">{{ resourceChain.resource.manual_status || '-' }}</el-descriptions-item>
        <el-descriptions-item label="废止日期">{{ formatDate(resourceChain.resource.abolish_date) }}</el-descriptions-item>
        <el-descriptions-item label="来源详情页" :span="2">
          <a v-if="resourceChain.resource.detail_url" :href="resourceChain.resource.detail_url" target="_blank">{{ resourceChain.resource.detail_url }}</a>
          <span v-else>-</span>
        </el-descriptions-item>
      </el-descriptions>

      <h3 class="section-title">匹配的本地文件</h3>
      <el-table :data="resourceChain.documents" height="220">
        <el-table-column prop="standard_no" label="编号" width="150" />
        <el-table-column prop="title" label="文件名称" min-width="320" show-overflow-tooltip />
        <el-table-column prop="source_status" label="来源状态" width="120" />
        <el-table-column prop="system_status" label="系统判断" width="140" />
        <el-table-column prop="manual_status" label="人工复核" width="120" />
        <el-table-column label="操作" width="110">
          <template #default="{ row }"><el-button size="small" @click.stop="openDocumentChainById(row.id)">文件链路</el-button></template>
        </el-table-column>
      </el-table>

      <chain-tables
        :versions="resourceChain.versions"
        :url-sources="resourceChain.url_sources"
        :sync-logs="resourceChain.sync_logs"
        :change-logs="resourceChain.change_logs"
        :evidences="resourceChain.evidences"
        :relations="resourceChain.relations"
        :alerts="resourceChain.alerts"
        @confirm-relation="confirmRelation"
      />
    </section>

    <section v-if="documentChain" class="chain-detail">
      <h3>文件链路详情</h3>
      <el-alert v-if="documentChain.processing_advice" :title="documentChain.processing_advice" type="warning" :closable="false" class="chain-advice" />
      <el-descriptions :column="2" border>
        <el-descriptions-item label="文件名称">{{ documentChain.document.title }}</el-descriptions-item>
        <el-descriptions-item label="标准编号">{{ documentChain.document.standard_no }}</el-descriptions-item>
        <el-descriptions-item label="规范编号">{{ documentChain.document.normalized_standard_no }}</el-descriptions-item>
        <el-descriptions-item label="当前版本">{{ documentChain.document.current_version_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="来源状态">{{ documentChain.document.source_status || '-' }}</el-descriptions-item>
        <el-descriptions-item label="系统判断">{{ documentChain.document.system_status || documentChain.document.valid_status }}</el-descriptions-item>
        <el-descriptions-item label="人工复核">{{ documentChain.document.manual_status || documentChain.document.review_status }}</el-descriptions-item>
        <el-descriptions-item label="元数据">{{ documentChain.document.metadata_status || '-' }}</el-descriptions-item>
      </el-descriptions>

      <h3 class="section-title">匹配的可信源标准</h3>
      <el-table :data="documentChain.resources" height="220">
        <el-table-column prop="standard_no" label="编号" width="150" />
        <el-table-column prop="standard_name" label="标准名称" min-width="320" show-overflow-tooltip />
        <el-table-column prop="source_status" label="来源状态" width="120" />
        <el-table-column prop="system_status" label="系统判断" width="140" />
        <el-table-column prop="abolish_date" label="废止日期" width="120" :formatter="dateFormatter" show-overflow-tooltip />
        <el-table-column label="操作" width="110">
          <template #default="{ row }"><el-button size="small" @click.stop="openResourceChainById(row.id)">资源链路</el-button></template>
        </el-table-column>
      </el-table>

      <chain-tables
        :versions="documentChain.versions"
        :url-sources="documentChain.url_sources"
        :sync-logs="documentChain.sync_logs"
        :change-logs="documentChain.change_logs"
        :evidences="documentChain.evidences"
        :relations="documentChain.relations"
        :alerts="documentChain.alerts"
        @confirm-relation="confirmRelation"
      />
    </section>
  </el-drawer>
</template>

<script setup lang="ts">
import { defineComponent, onMounted, reactive, ref } from 'vue'
import { Aim, Bell, CircleCheck, DataBoard, Document, Download, Files, Link, Medal, Plus, Refresh, Search, Setting, Switch, Warning } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api, type Alert, type CollectionTask, type DocumentChain, type DocumentItem, type DocumentVersion, type Page, type ResourceChain, type SourceCategory, type SourceStatusSyncLog, type StandardChangeLog, type StandardFileMatch, type StandardResource, type StorageBrowse, type StorageStatus, type SystemSetting, type TrustedSource, type UrlSource } from './api'

function formatDateTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return String(value).replace('T', ' ').replace(/\.\d+/, '')
  }
  const pad = (num: number) => String(num).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

function formatDate(value?: string | null) {
  if (!value) return '-'
  const normalized = formatDateTime(value)
  return normalized === '-' ? normalized : normalized.slice(0, 10)
}

function dateTimeFormatter(_row: unknown, _column: unknown, value?: string | null) {
  return formatDateTime(value)
}

function dateFormatter(_row: unknown, _column: unknown, value?: string | null) {
  return formatDate(value)
}

const ChainTables = defineComponent({
  props: {
    versions: { type: Array, required: true },
    urlSources: { type: Array, required: true },
    syncLogs: { type: Array, required: true },
    changeLogs: { type: Array, required: true },
    evidences: { type: Array, required: true },
    relations: { type: Array, required: true },
    alerts: { type: Array, required: true },
  },
  methods: { dateTimeFormatter },
  template: `
    <h3 class="section-title">来源 URL</h3>
    <el-table :data="urlSources" height="180">
      <el-table-column prop="source_name" label="来源名称" width="220" show-overflow-tooltip />
      <el-table-column prop="url" label="URL" min-width="360" show-overflow-tooltip />
      <el-table-column prop="status" label="状态" width="100" />
      <el-table-column prop="last_checked_at" label="最后检查" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
    </el-table>

    <h3 class="section-title">版本记录</h3>
    <el-table :data="versions" height="220">
      <el-table-column prop="version_no" label="版本" width="90" />
      <el-table-column prop="file_name" label="文件名" min-width="280" show-overflow-tooltip />
      <el-table-column prop="change_type" label="变化" width="100" />
      <el-table-column prop="is_current" label="当前" width="90" />
      <el-table-column prop="file_hash" label="文件哈希" min-width="240" show-overflow-tooltip />
      <el-table-column prop="downloaded_at" label="下载时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
    </el-table>

    <h3 class="section-title">状态同步记录</h3>
    <el-table :data="syncLogs" height="220">
      <el-table-column prop="old_status" label="原状态" width="140" />
      <el-table-column prop="new_status" label="新状态" width="140" />
      <el-table-column prop="sync_action" label="动作" width="150" />
      <el-table-column prop="sync_reason" label="原因/证据" min-width="420" show-overflow-tooltip />
      <el-table-column prop="synced_at" label="同步时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
    </el-table>

    <h3 class="section-title">变更记录</h3>
    <el-table :data="changeLogs" height="220">
      <el-table-column prop="field_name" label="字段" width="150" />
      <el-table-column prop="change_type" label="变化类型" width="130" />
      <el-table-column prop="old_value" label="旧值" min-width="220" show-overflow-tooltip />
      <el-table-column prop="new_value" label="新值" min-width="220" show-overflow-tooltip />
      <el-table-column prop="evidence_summary" label="证据说明" min-width="260" show-overflow-tooltip />
      <el-table-column prop="detected_at" label="发现时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
    </el-table>

    <h3 class="section-title">证据记录</h3>
    <el-table :data="evidences" height="220">
      <el-table-column prop="source_name" label="来源网站" width="160" />
      <el-table-column prop="source_level" label="等级" width="80" />
      <el-table-column prop="raw_status_text" label="原始状态" width="120" />
      <el-table-column prop="parsed_status" label="解析结果" width="140" />
      <el-table-column prop="evidence_note" label="证据说明" min-width="360" show-overflow-tooltip />
      <el-table-column prop="source_url" label="原始 URL" min-width="280" show-overflow-tooltip />
      <el-table-column prop="captured_at" label="抓取时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
    </el-table>

    <h3 class="section-title">替代/相关关系</h3>
    <el-table :data="relations" height="180">
      <el-table-column prop="current_standard_no" label="当前标准" width="160" />
      <el-table-column prop="related_standard_no" label="关联标准" width="160" />
      <el-table-column prop="relation_type" label="关系类型" width="120" />
      <el-table-column prop="relation_text" label="关系原文" min-width="360" show-overflow-tooltip />
      <el-table-column prop="source_url" label="来源 URL" min-width="260" show-overflow-tooltip />
      <el-table-column prop="is_manual_confirmed" label="人工确认" width="100" />
      <el-table-column label="操作" width="110">
        <template #default="{ row }">
          <el-button size="small" :disabled="row.is_manual_confirmed" @click="$emit('confirm-relation', row.id)">确认关系</el-button>
        </template>
      </el-table-column>
    </el-table>

    <h3 class="section-title">提醒记录</h3>
    <el-table :data="alerts" height="180">
      <el-table-column prop="alert_level" label="等级" width="90" />
      <el-table-column prop="alert_type" label="类型" width="140" />
      <el-table-column prop="message" label="消息" min-width="360" show-overflow-tooltip />
      <el-table-column prop="status" label="状态" width="110" />
      <el-table-column prop="created_at" label="创建时间" width="170" :formatter="dateTimeFormatter" show-overflow-tooltip />
    </el-table>
  `,
})

const activeView = ref('dashboard')
const urlSources = ref<UrlSource[]>([])
const documents = ref<DocumentItem[]>([])
const reviewDocuments = ref<DocumentItem[]>([])
const alerts = ref<Alert[]>([])
const versions = ref<DocumentVersion[]>([])
const systemSettings = ref<SystemSetting[]>([])
const collectionTasks = ref<CollectionTask[]>([])
const storageStatus = ref<StorageStatus | null>(null)
const trustedSources = ref<TrustedSource[]>([])
const sourceCategories = ref<SourceCategory[]>([])
const trustedResources = ref<StandardResource[]>([])
const fileMatches = ref<StandardFileMatch[]>([])
const sourceChanges = ref<StandardChangeLog[]>([])
const statusSyncLogs = ref<SourceStatusSyncLog[]>([])
const resourceChain = ref<ResourceChain | null>(null)
const documentChain = ref<DocumentChain | null>(null)
const chainDrawerVisible = ref(false)
const chainTitle = ref('链路详情')
const urlTotal = ref(0)
const documentTotal = ref(0)
const alertTotal = ref(0)
const resourceTotal = ref(0)
const pendingReviewCount = ref(0)
const pendingAlertCount = ref(0)

const showUrlDialog = ref(false)
const showDocumentDialog = ref(false)
const storagePickerVisible = ref(false)
const storageBrowse = ref<StorageBrowse>({ directories: [] })
const checkingSourceId = ref<number | null>(null)
const checkingAll = ref(false)
const syncingTrustedSource = ref(false)
const discoveringCategories = ref(false)
const syncingPendingCategories = ref(false)
const selectedDocumentId = ref<number | undefined>()
const selectedTrustedSourceId = ref<number | undefined>()
const selectedSourceCategoryId = ref<string | undefined>()
const collectionActiveTab = ref('sources')
const trustedResourceActiveTab = ref('resources')
const dashboardTableHeight = 'calc(100vh - 210px)'
const pagedTableHeight = 'calc(100vh - 260px)'
const trustedResourceTableHeight = 'calc(100vh - 540px)'
const sourceQueueTableHeight = '220px'
const collectionTableHeight = 'calc(100vh - 230px)'
const plainTableHeight = 'calc(100vh - 170px)'

const urlQuery = reactive({ page: 1, page_size: 50, q: '', status: '', check_frequency: '' })
const documentQuery = reactive({
  page: 1,
  page_size: 50,
  q: '',
  source_status: '',
  system_status: '',
  manual_status: '',
  valid_status: '',
  review_status: '',
  doc_type: '',
})
const alertQuery = reactive({ page: 1, page_size: 50, q: '', status: '未处理' })
const resourceQuery = reactive({ page: 1, page_size: 50, q: '', source_status: '', resource_type: '' })

const urlForm = reactive({ url: '', source_name: '', source_unit: '', source_type: '文件直链', category: '标准规范', check_frequency: 'manual' })
const documentForm = reactive({ title: '', standard_no: '', category: '', issuing_authority: '' })

async function loadUrlSources() {
  const res = await api.get<Page<UrlSource>>('/url-sources/page', { params: urlQuery })
  urlSources.value = res.data.items
  urlTotal.value = res.data.total
}

async function loadDocuments() {
  const res = await api.get<Page<DocumentItem>>('/documents/page', { params: documentQuery })
  documents.value = res.data.items
  documentTotal.value = res.data.total
}

async function loadAlerts() {
  const res = await api.get<Page<Alert>>('/alerts/page', { params: alertQuery })
  alerts.value = res.data.items
  alertTotal.value = res.data.total
}

async function loadCounts() {
  const pendingDocs = await api.get<Page<DocumentItem>>('/documents/page', { params: { page: 1, page_size: 1, system_status: '待复核' } })
  const pendingAlerts = await api.get<Page<Alert>>('/alerts/page', { params: { page: 1, page_size: 1, status: '未处理' } })
  pendingReviewCount.value = pendingDocs.data.total
  pendingAlertCount.value = pendingAlerts.data.total
}

async function loadAll() {
  await Promise.all([loadUrlSources(), loadDocuments(), loadAlerts(), loadCounts(), loadCollectionTasks()])
}

function switchView(view: string) {
  activeView.value = view
  if (view === 'documents') loadDocuments()
  if (view === 'versions') loadDocuments()
  if (view === 'review') loadPendingReview()
  if (view === 'settings') loadSettings()
  if (view === 'collection') {
    loadUrlSources()
    loadCollectionTasks()
  }
  if (view === 'trustedResources') loadTrustedResources()
  if (view === 'fileMatches') loadFileMatches()
  if (view === 'sourceChanges') loadSourceChanges()
  if (view === 'statusSyncLogs') loadStatusSyncLogs()
}

async function createUrlSource() {
  await api.post('/url-sources', urlForm)
  showUrlDialog.value = false
  Object.assign(urlForm, { url: '', source_name: '', source_unit: '', source_type: '文件直链', category: '标准规范', check_frequency: 'manual' })
  await loadUrlSources()
}

async function checkSource(id: number) {
  checkingSourceId.value = id
  try {
    const res = await api.post(`/url-sources/${id}/check`)
    ElMessage.success(res.data.message)
    await loadAll()
  } finally {
    checkingSourceId.value = null
  }
}

async function checkAllSources() {
  checkingAll.value = true
  try {
    const res = await api.post('/url-sources/check-all')
    ElMessage.success(`已检查 ${res.data.total} 个非手动 URL`)
    await loadAll()
  } finally {
    checkingAll.value = false
  }
}

async function loadCollectionTasks() {
  const res = await api.get<CollectionTask[]>('/collection-tasks')
  collectionTasks.value = res.data
}

async function createUrlCheckTask() {
  checkingAll.value = true
  try {
    const res = await api.post<CollectionTask>('/collection-tasks/url-check', { include_manual: false, batch_size: 50 })
    ElMessage.success(`已创建后台检查任务 #${res.data.id}`)
    await loadCollectionTasks()
  } finally {
    checkingAll.value = false
  }
}

async function resumeCollectionTask(id: number) {
  await api.post<CollectionTask>(`/collection-tasks/${id}/resume`)
  ElMessage.success(`后台任务 #${id} 已继续执行`)
  await loadCollectionTasks()
}

function taskPercent(row: CollectionTask) {
  if (!row.total) return row.status === 'finished' ? 100 : 0
  return Math.min(100, Math.round((row.processed / row.total) * 100))
}

async function createDocument() {
  await api.post('/documents', documentForm)
  showDocumentDialog.value = false
  Object.assign(documentForm, { title: '', standard_no: '', category: '', issuing_authority: '' })
  await loadDocuments()
}

async function reviewDocument(id: number, manual_status: string) {
  await api.patch(`/documents/${id}`, { manual_status, metadata_status: '人工确认' })
  ElMessage.success('状态已更新')
  if (activeView.value === 'review') {
    await Promise.all([loadPendingReview(), loadCounts()])
  } else {
    await Promise.all([loadDocuments(), loadCounts()])
  }
}

async function setAlertStatus(id: number, status: string) {
  await api.patch(`/alerts/${id}`, { status, handled_by: 'admin' })
  ElMessage.success('提醒状态已更新')
  await Promise.all([loadAlerts(), loadCounts()])
}

async function selectDocument(row: DocumentItem) {
  selectedDocumentId.value = row.id
  await loadVersions()
}

async function openResourceChain(row: StandardResource) {
  await openResourceChainById(row.id)
}

async function openResourceChainById(id?: number) {
  if (!id) return
  const res = await api.get<ResourceChain>(`/standard-resources/${id}/chain`)
  resourceChain.value = res.data
  documentChain.value = null
  chainTitle.value = `资源链路：${res.data.resource.standard_no || ''} ${res.data.resource.standard_name}`
  chainDrawerVisible.value = true
}

async function openDocumentChain(row: DocumentItem) {
  selectedDocumentId.value = row.id
  await openDocumentChainById(row.id)
}

async function openDocumentChainById(id?: number) {
  if (!id) return
  selectedDocumentId.value = id
  const res = await api.get<DocumentChain>(`/documents/${id}/chain`)
  documentChain.value = res.data
  resourceChain.value = null
  chainTitle.value = `文件链路：${res.data.document.standard_no || ''} ${res.data.document.title}`
  chainDrawerVisible.value = true
}

async function loadVersions() {
  if (!selectedDocumentId.value) return
  const res = await api.get<DocumentVersion[]>(`/documents/${selectedDocumentId.value}/versions`)
  versions.value = res.data
}

async function loadPendingReview() {
  const res = await api.get<Page<DocumentItem>>('/documents/page', {
    params: { page: 1, page_size: documentQuery.page_size, system_status: '待复核' },
  })
  reviewDocuments.value = res.data.items
}

async function confirmRelation(id: number) {
  await api.patch(`/standard-relations/${id}`, { is_manual_confirmed: true })
  ElMessage.success('替代/相关关系已确认')
  if (resourceChain.value) {
    await openResourceChainById(resourceChain.value.resource.id)
  } else if (documentChain.value) {
    await openDocumentChainById(documentChain.value.document.id)
  }
}

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
  await api.patch(`/settings/${key}`, { value })
  ElMessage.success('设置已保存')
  await loadSettings()
}

async function chooseStorageRoot(row: SystemSetting) {
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

async function loadTrustedResources() {
  if (!trustedSources.value.length) {
    await loadTrustedSources()
  }
  if (selectedTrustedSourceId.value) {
    await loadSourceCategories()
  }
  const res = await api.get<Page<StandardResource>>('/standard-resources/page', {
    params: { ...resourceQuery, source_id: selectedTrustedSourceId.value },
  })
  trustedResources.value = res.data.items
  resourceTotal.value = res.data.total
}

async function loadTrustedSources() {
  const res = await api.get<TrustedSource[]>('/trusted-sources')
  trustedSources.value = res.data
  if (!selectedTrustedSourceId.value && res.data.length) {
    selectedTrustedSourceId.value = res.data[0].id
  }
  if (selectedTrustedSourceId.value) {
    await loadSourceCategories()
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
      max_pages: 1,
      include_detail: false,
      only_pending_categories: true,
      category_limit: 5,
    })
    ElMessage.success(`同步分类 ${res.data.categories} 个，资源 ${res.data.items} 条，新增 ${res.data.created} 条，跳过详情 ${res.data.skipped_existing_detail} 条`)
    await loadSourceCategories()
    await loadTrustedResources()
  } finally {
    syncingPendingCategories.value = false
  }
}

async function loadFileMatches() {
  const res = await api.get<StandardFileMatch[]>('/standard-file-matches')
  fileMatches.value = res.data
}

async function runFileMatch() {
  const res = await api.post('/standard-file-matches/run')
  ElMessage.success(`匹配 ${res.data.matched} 条，跳过 ${res.data.skipped} 条`)
  await loadFileMatches()
}

async function loadSourceChanges() {
  const res = await api.get<StandardChangeLog[]>('/standard-change-logs')
  sourceChanges.value = res.data
}

async function loadStatusSyncLogs() {
  const res = await api.get<SourceStatusSyncLog[]>('/source-status-sync-logs')
  statusSyncLogs.value = res.data
}

onMounted(loadAll)
</script>
