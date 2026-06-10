<script setup lang="ts">
import AuditLogDrawer from '../governance/AuditLogDrawer.vue'
import EvidenceChainDrawer from '../governance/EvidenceChainDrawer.vue'
import DecisionReasonDrawer from './DecisionReasonDrawer.vue'
import FileObjectDrawer from '../file/FileObjectDrawer.vue'
import { useGlobalDrawers } from '../../composables/useGlobalDrawers'

const { state } = useGlobalDrawers()
</script>

<template>
  <EvidenceChainDrawer
    v-model:visible="state.evidenceVisible"
    :resource-id="state.evidenceResourceId"
    :document-id="state.evidenceDocumentId"
  />
  <AuditLogDrawer
    v-model:visible="state.auditVisible"
    :target-type="state.auditTargetType"
    :target-id="state.auditTargetId"
    :process-type="state.auditProcessType"
  />
  <DecisionReasonDrawer v-model:visible="state.decisionVisible" :resource-id="state.decisionResourceId" />
  <FileObjectDrawer v-model:visible="state.fileObjectVisible" :file-object-id="state.fileObjectId" />
</template>
