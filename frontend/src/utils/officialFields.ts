import { formatDate, formatDateTime } from './formatters'

function parseJsonObject(value?: string | null): Record<string, unknown> {
  if (!value) return {}
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : {}
  } catch {
    return {}
  }
}

export function jsonPretty(value?: string | null) {
  if (!value) return '-'
  try {
    return JSON.stringify(JSON.parse(value), null, 2)
  } catch {
    return value
  }
}

export function officialLinkEntries(catalogText?: string | null): [string, string][] {
  const links = parseJsonObject(catalogText).official_links
  if (!links || typeof links !== 'object' || Array.isArray(links)) return []
  return Object.entries(links as Record<string, unknown>).filter(
    (entry): entry is [string, string] => typeof entry[1] === 'string' && entry[1].length > 0,
  )
}

const officialLinkLabels: Record<string, string> = {
  std_detail: '国家平台详情',
  openstd_detail: '公开标准详情',
  online_preview: '在线预览',
  download_page: '下载入口',
  feedback: '意见反馈',
}

export function officialLinkLabel(key: string) {
  return officialLinkLabels[key] || key
}

const officialFieldLabels: Record<string, string> = {
  C_STD_CODE: '标准编号',
  C_C_NAME: '标准名称',
  C_EN_NAME: '英文名称',
  STD_NATURE: '标准性质',
  STATE: '官方状态',
  ISSUE_DATE: '发布日期',
  ACT_DATE: '实施日期',
  ABOLISH_DATE: '废止日期',
  ICS_CODE: 'ICS 分类',
  CCS_CODE: '中国标准分类号',
  C_PLAN_CODE: '计划号',
  DRAFT_UNIT: '起草单位',
  TECH_COMMITTEE: '归口单位',
  REPLACE_STD: '代替标准',
  ADOPT_STD: '采用国际标准',
  id: '官方记录 ID',
}

const officialFieldOrder = [
  'C_EN_NAME',
  'STD_NATURE',
  'STATE',
  'ISSUE_DATE',
  'ACT_DATE',
  'ABOLISH_DATE',
  'ICS_CODE',
  'CCS_CODE',
  'C_PLAN_CODE',
  'DRAFT_UNIT',
  'TECH_COMMITTEE',
  'REPLACE_STD',
  'ADOPT_STD',
]

export function officialFieldEntries(catalogText?: string | null) {
  const fields = parseJsonObject(catalogText).gb_fields
  if (!fields || typeof fields !== 'object' || Array.isArray(fields)) return []
  const record = fields as Record<string, unknown>
  return officialFieldOrder
    .filter((key) => record[key] !== null && record[key] !== undefined && String(record[key]).trim() !== '')
    .map((key) => ({
      key,
      label: officialFieldLabels[key] || key,
      value: String(record[key]),
      span: 1,
    }))
}

export function openExternalUrl(url?: string | null) {
  if (!url) return
  window.open(url, '_blank', 'noopener')
}

export { formatDate, formatDateTime, parseJsonObject }
