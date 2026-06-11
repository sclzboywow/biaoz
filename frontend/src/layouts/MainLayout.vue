<script setup lang="ts">
import { computed, provide } from 'vue'
import { useRoute } from 'vue-router'
import {
  Aim,
  Bell,
  Box,
  CircleCheck,
  Collection,
  DataBoard,
  Document,
  Download,
  Files,
  Link,
  Management,
  Medal,
  Monitor,
  Reading,
  Search,
  Setting,
  Switch,
  TrendCharts,
  Warning,
} from '@element-plus/icons-vue'
import GlobalDrawersHost from '../components/common/GlobalDrawersHost.vue'
import DocumentCreateDialog from '../components/common/DocumentCreateDialog.vue'
import UrlCreateDialog from '../components/common/UrlCreateDialog.vue'
import { useGlobalDrawers } from '../composables/useGlobalDrawers'
import { createGlobalDialogsState, globalDialogsKey } from '../composables/useGlobalDialogs'
import { usePermissions, type AppRole } from '../composables/usePermissions'

const route = useRoute()
const { role, setRole } = usePermissions()
const drawers = useGlobalDrawers()
provide('globalDrawers', drawers)

const { showUrlDialog, showDocumentDialog, api: globalDialogsApi } = createGlobalDialogsState()
provide(globalDialogsKey, globalDialogsApi)

const activeMenu = computed(() => route.path)
</script>

<template>
  <el-container class="app-shell">
    <el-aside width="260px" class="sidebar">
      <div class="brand">标准规范文件动态管理系统</div>
      <el-menu :default-active="activeMenu" router background-color="#17202a" text-color="#d5dde5" active-text-color="#ffffff">
        <el-sub-menu index="workbench">
          <template #title><el-icon><DataBoard /></el-icon><span>工作台</span></template>
          <el-menu-item index="/dashboard/governance"><el-icon><TrendCharts /></el-icon><span>治理总览</span></el-menu-item>
          <el-menu-item index="/dashboard/supervision"><el-icon><Monitor /></el-icon><span>自动监督中心</span></el-menu-item>
          <el-menu-item index="/dashboard/today-tasks"><el-icon><Collection /></el-icon><span>今日任务</span></el-menu-item>
          <el-menu-item index="/dashboard/high-risk"><el-icon><Warning /></el-icon><span>高风险异常</span></el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="source-governance">
          <template #title><el-icon><Management /></el-icon><span>来源治理</span></template>
          <el-menu-item index="/source-governance/sources"><el-icon><Medal /></el-icon><span>来源主档</span></el-menu-item>
          <el-menu-item index="/source-governance/url-sources"><el-icon><Link /></el-icon><span>URL 来源治理</span></el-menu-item>
          <el-menu-item index="/source-governance/raw-records"><el-icon><Document /></el-icon><span>原始记录池</span></el-menu-item>
          <el-menu-item index="/source-governance/candidates"><el-icon><Search /></el-icon><span>候选记录池</span></el-menu-item>
          <el-menu-item index="/source-governance/health"><el-icon><TrendCharts /></el-icon><span>来源健康度</span></el-menu-item>
          <el-menu-item index="/source-governance/blacklist"><el-icon><Warning /></el-icon><span>黑名单/低可信来源</span></el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="collection">
          <template #title><el-icon><Download /></el-icon><span>采集归档</span></template>
          <el-menu-item index="/collection/tasks"><el-icon><Download /></el-icon><span>文件采集任务</span></el-menu-item>
          <el-menu-item index="/collection/runtime"><el-icon><Monitor /></el-icon><span>采集运行控制台</span></el-menu-item>
          <el-menu-item index="/collection/ocr-queue"><el-icon><Reading /></el-icon><span>OCR 下载队列</span></el-menu-item>
          <el-menu-item index="/collection/file-objects"><el-icon><Box /></el-icon><span>文件对象库</span></el-menu-item>
          <el-menu-item index="/collection/archive"><el-icon><Document /></el-icon><span>文件归档库</span></el-menu-item>
          <el-menu-item index="/collection/versions"><el-icon><Files /></el-icon><span>版本管理</span></el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="standards">
          <template #title><el-icon><Medal /></el-icon><span>标准主库</span></template>
          <el-menu-item index="/standards/resources"><el-icon><Medal /></el-icon><span>标准资源主库</span></el-menu-item>
          <el-menu-item index="/standards/file-matches"><el-icon><Aim /></el-icon><span>本地文件匹配</span></el-menu-item>
          <el-menu-item index="/standards/evidence"><el-icon><Link /></el-icon><span>证据链</span></el-menu-item>
          <el-menu-item index="/standards/relations"><el-icon><Switch /></el-icon><span>替代关系</span></el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="exceptions">
          <template #title><el-icon><Bell /></el-icon><span>状态异常</span></template>
          <el-menu-item index="/exceptions/status-sync"><el-icon><Switch /></el-icon><span>状态同步</span></el-menu-item>
          <el-menu-item index="/exceptions/changes"><el-icon><Warning /></el-icon><span>变更监测</span></el-menu-item>
          <el-menu-item index="/exceptions/alerts"><el-icon><Bell /></el-icon><span>异常提醒</span></el-menu-item>
          <el-menu-item index="/exceptions/pending"><el-icon><CircleCheck /></el-icon><span>待处理异常</span></el-menu-item>
          <el-menu-item index="/exceptions/audit-logs"><el-icon><Document /></el-icon><span>流程审计日志</span></el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="settings">
          <template #title><el-icon><Setting /></el-icon><span>系统配置</span></template>
          <el-menu-item index="/settings/general"><span>系统设置</span></el-menu-item>
          <el-menu-item index="/settings/source-rules"><span>来源规则</span></el-menu-item>
          <el-menu-item index="/settings/ocr"><span>OCR 配置</span></el-menu-item>
          <el-menu-item index="/settings/field-mapping"><span>字段映射</span></el-menu-item>
          <el-menu-item index="/settings/rate-limit"><span>采集限速</span></el-menu-item>
          <el-menu-item index="/settings/storage"><span>存储配置</span></el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="legacy">
          <template #title><span>旧版入口</span></template>
          <el-menu-item index="/legacy/overview"><span>旧版总览</span></el-menu-item>
          <el-menu-item index="/dashboard/overview"><span>工作台总览</span></el-menu-item>
        </el-sub-menu>
      </el-menu>

      <div class="role-switcher">
        <span>角色</span>
        <el-select :model-value="role" size="small" style="width: 120px" @change="(v: AppRole) => setRole(v)">
          <el-option label="管理员" value="admin" />
          <el-option label="操作员" value="operator" />
          <el-option label="只读" value="readonly" />
        </el-select>
      </div>
    </el-aside>

    <el-main class="main">
      <router-view />
    </el-main>
  </el-container>

  <GlobalDrawersHost />
  <UrlCreateDialog v-model:visible="showUrlDialog" />
  <DocumentCreateDialog v-model:visible="showDocumentDialog" />
</template>

<style scoped>
.role-switcher {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 16px;
  color: #d5dde5;
  font-size: 13px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}
</style>
