import { formatDate, formatDateTime } from './formatters'

export function dateTimeFormatter(_row: unknown, _column: unknown, value?: string | null) {
  return formatDateTime(value)
}

export function dateFormatter(_row: unknown, _column: unknown, value?: string | null) {
  return formatDate(value)
}

export function fileSizeMbFormatter(_row: unknown, _column: unknown, value?: number | null) {
  if (value === null || value === undefined) return '-'
  return `${(Number(value) / 1024 / 1024).toFixed(2)} MB`
}

type StatusLike = {
  source_status?: string | null
  system_status?: string | null
  manual_status?: string | null
  valid_status?: string | null
  review_status?: string | null
}

export function sourceStatusFormatter(row: StatusLike) {
  return row.source_status || '-'
}

export function systemStatusFormatter(row: StatusLike) {
  return row.system_status || row.valid_status || '-'
}

export function manualStatusFormatter(row: StatusLike) {
  return row.manual_status || row.review_status || '-'
}
