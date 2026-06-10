import { inject, provide, ref, type InjectionKey } from 'vue'

export type GlobalDialogsApi = {
  openUrlCreate: () => void
  openDocumentCreate: () => void
}

export const globalDialogsKey: InjectionKey<GlobalDialogsApi> = Symbol('globalDialogs')

export function createGlobalDialogsState() {
  const showUrlDialog = ref(false)
  const showDocumentDialog = ref(false)

  const api: GlobalDialogsApi = {
    openUrlCreate: () => {
      showUrlDialog.value = true
    },
    openDocumentCreate: () => {
      showDocumentDialog.value = true
    },
  }

  return { showUrlDialog, showDocumentDialog, api }
}

export function provideGlobalDialogs() {
  const dialogs = createGlobalDialogsState()
  provide(globalDialogsKey, dialogs.api)
  return dialogs
}

export function useGlobalDialogs() {
  const dialogs = inject(globalDialogsKey)
  if (!dialogs) throw new Error('globalDialogs not provided')
  return dialogs
}
