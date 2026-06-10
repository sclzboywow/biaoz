import { formatDate } from './formatters'

const changeFieldLabels: Record<string, string> = {
  standard_no: '标准编号',
  standard_name: '标准名称',
  source_status: '可信源状态',
  publish_date: '发布日期',
  effective_date: '实施日期',
  abolish_date: '废止日期',
  change_info: '变更信息',
  detail_hash: '详情页指纹',
}

export function changeFieldFormatter(row: { field_name: string }) {
  return changeFieldLabels[row.field_name] || row.field_name
}

export function changeValueFormatter(row: { field_name: string }, _column: unknown, value?: string | null) {
  if (row.field_name === 'detail_hash') return value ? '页面内容已变化' : '无记录'
  if (value === null || value === undefined || value === '') return '无记录'
  if (['publish_date', 'effective_date', 'abolish_date'].includes(row.field_name)) return formatDate(value)
  if (/^[a-f0-9]{48,}$/i.test(String(value))) return '内容指纹'
  return String(value)
}

export function changeDocumentFormatter(row: { document_title?: string | null; document_id?: number | null }) {
  return row.document_title || (row.document_id ? `文件 ${row.document_id}` : '未关联本地文件')
}

export function changeVersionFormatter(row: {
  version_no?: string | null
  file_name?: string | null
  document_version_id?: number | null
}) {
  if (row.version_no && row.file_name) return `${row.version_no} / ${row.file_name}`
  if (row.file_name) return row.file_name
  if (row.document_version_id) return `版本 ${row.document_version_id}`
  return '未关联版本'
}

export function changeEvidenceFormatter(row: {
  field_name: string
  document_id?: number | null
  standard_resource_id?: number | null
}) {
  const field = changeFieldFormatter(row)
  if (row.field_name === 'detail_hash') return '可信源详情页内容发生变化'
  const target = row.document_id ? `本地文件 ${row.document_id}` : `可信资源 ${row.standard_resource_id}`
  return `${target} 的${field}发生变化`
}
