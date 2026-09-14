import http from './http'
import type { ApiResult } from './http'
import type { PageResult } from './knowledge'

export interface TemplateOut {
  id: number
  name: string
  category: string | null
  file_name: string | null
  file_size: number
  variables: string[]
  description: string | null
  uploader: string | null
  created_at: string | null
  updated_at: string | null
}

export interface TemplatePage extends PageResult<TemplateOut> {
  categories: string[]
}

export interface ContractGenerateOut {
  template_id: number
  template_name: string
  file_name: string
  download_url: string
  missing_variables: string[]
}

/** 模板库列表（含解析出的占位变量与全部分类） */
export function listTemplates(params: { category?: string; page?: number; page_size?: number }) {
  return http.get<never, ApiResult<TemplatePage>>('/templates', { params })
}

/** 导入模板（.docx，含 {{ 变量 }} 占位符） */
export function uploadTemplate(form: {
  file: File
  name?: string
  category?: string
  description?: string
}) {
  const data = new FormData()
  data.append('file', form.file)
  if (form.name) data.append('name', form.name)
  if (form.category) data.append('category', form.category)
  if (form.description) data.append('description', form.description)
  return http.post<never, ApiResult<TemplateOut>>('/templates', data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function deleteTemplate(id: number) {
  return http.delete<never, ApiResult<{ id: number }>>(`/templates/${id}`)
}

/** 合同生成：按模板填充变量（确定性链路，不调 LLM） */
export function generateContract(templateId: number, variables: Record<string, string>) {
  return http.post<never, ApiResult<ContractGenerateOut>>('/generate/contract', {
    template_id: templateId,
    variables,
  })
}

/** 下载 URL（前端直接用 <a href> 触发，携带 token 由 http 层不方便，故拼相对路径 + token 查询不适用，改用 blob 下载见下） */
export function fileDownloadUrl(fileName: string) {
  return `/api/v1/generate/files/${encodeURIComponent(fileName)}`
}

/** 带鉴权下载生成产物 */
export async function downloadGeneratedFile(fileName: string) {
  const base = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const token = localStorage.getItem('token') || ''
  const resp = await fetch(`${base}/generate/files/${encodeURIComponent(fileName)}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!resp.ok) throw new Error(`下载失败（HTTP ${resp.status}）`)
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
