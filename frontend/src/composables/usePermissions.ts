import { computed, ref } from 'vue'

export type AppRole = 'admin' | 'operator' | 'readonly'

const ROLE_KEY = 'biaoz_app_role'

const sensitiveActions = new Set([
  'settings',
  'source-rules',
  'ocr-config',
  'field-mapping',
  'rate-limit',
  'storage-config',
  'blacklist',
  'override-decision',
  'delete-record',
])

export function usePermissions() {
  const role = ref<AppRole>((localStorage.getItem(ROLE_KEY) as AppRole) || 'admin')

  function setRole(next: AppRole) {
    role.value = next
    localStorage.setItem(ROLE_KEY, next)
  }

  const isReadonly = computed(() => role.value === 'readonly')
  const isAdmin = computed(() => role.value === 'admin')

  function can(action: string) {
    if (role.value === 'admin') return true
    if (role.value === 'readonly') return false
    return !sensitiveActions.has(action)
  }

  return { role, setRole, can, isReadonly, isAdmin }
}
