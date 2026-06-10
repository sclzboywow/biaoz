export function formatDateTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function formatDate(value?: string | null) {
  if (!value) return '-'
  const normalized = formatDateTime(value)
  return normalized === '-' ? normalized : normalized.slice(0, 10)
}

export function formatFileSize(size?: number | null) {
  if (size == null) return '-'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(2)} MB`
}

export function distributionEntries(record?: Record<string, number>) {
  if (!record) return []
  return Object.entries(record).sort((a, b) => b[1] - a[1])
}
