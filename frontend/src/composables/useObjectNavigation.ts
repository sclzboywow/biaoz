import { inject } from 'vue'
import { useRouter } from 'vue-router'
import type { GlobalDrawers } from './useGlobalDrawers'

export function useObjectNavigation() {
  const router = useRouter()
  const drawers = inject<GlobalDrawers>('globalDrawers')

  function goStandardDetail(resourceId: number, tab?: string) {
    router.push({ name: 'standard-detail', params: { id: resourceId }, query: tab ? { tab } : {} })
  }

  function goSourceMaster(sourceId: number) {
    router.push({ name: 'source-master-detail', params: { id: sourceId } })
  }

  function goFileArchive(documentId?: number) {
    router.push({ name: 'file-archive', query: documentId ? { highlight: String(documentId) } : {} })
  }

  function openEvidence(resourceId?: number, documentId?: number) {
    drawers?.openEvidenceChain({ resourceId, documentId })
  }

  function openAudit(targetType: string, targetId: number, processType?: string) {
    drawers?.openAuditLog({ targetType, targetId, processType })
  }

  function openDecision(resourceId: number) {
    drawers?.openDecisionReason(resourceId)
  }

  function openFileObject(fileObjectId: number) {
    drawers?.openFileObject(fileObjectId)
  }

  return {
    goStandardDetail,
    goSourceMaster,
    goFileArchive,
    openEvidence,
    openAudit,
    openDecision,
    openFileObject,
  }
}
