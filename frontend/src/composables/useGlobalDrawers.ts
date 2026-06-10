import { reactive } from 'vue'

export type GlobalDrawerState = {
  evidenceVisible: boolean
  evidenceResourceId?: number
  evidenceDocumentId?: number
  auditVisible: boolean
  auditTargetType?: string
  auditTargetId?: number
  auditProcessType?: string
  decisionVisible: boolean
  decisionResourceId?: number
  fileObjectVisible: boolean
  fileObjectId?: number
  chainVisible: boolean
  chainResourceId?: number
  chainDocumentId?: number
}

const state = reactive<GlobalDrawerState>({
  evidenceVisible: false,
  auditVisible: false,
  decisionVisible: false,
  fileObjectVisible: false,
  chainVisible: false,
})

export function useGlobalDrawers() {
  function openEvidenceChain(opts: { resourceId?: number; documentId?: number }) {
    state.evidenceResourceId = opts.resourceId
    state.evidenceDocumentId = opts.documentId
    state.evidenceVisible = true
  }

  function openAuditLog(opts: { targetType: string; targetId: number; processType?: string }) {
    state.auditTargetType = opts.targetType
    state.auditTargetId = opts.targetId
    state.auditProcessType = opts.processType
    state.auditVisible = true
  }

  function openDecisionReason(resourceId: number) {
    state.decisionResourceId = resourceId
    state.decisionVisible = true
  }

  function openFileObject(fileObjectId: number) {
    state.fileObjectId = fileObjectId
    state.fileObjectVisible = true
  }

  function openChain(opts: { resourceId?: number; documentId?: number }) {
    state.chainResourceId = opts.resourceId
    state.chainDocumentId = opts.documentId
    state.chainVisible = true
  }

  return {
    state,
    openEvidenceChain,
    openAuditLog,
    openDecisionReason,
    openFileObject,
    openChain,
  }
}

export type GlobalDrawers = ReturnType<typeof useGlobalDrawers>
