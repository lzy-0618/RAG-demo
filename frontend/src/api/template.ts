import http from './http'
import type { ApiResult } from './http'
import type { PageResult } from './knowledge'

/** 字段 schema：AI 识别 + 人工复核后确定的一项待填内容 */
export interface TemplateField {
  key: string
  label: string
  type: string
  required: boolean
  default: string
  options: string[]
  anchor: string
  candidate_id: string
  paragraph_text: string
  confidence: number
  reason: string
}

/** 结构化状态机：待识别 → 识别中 → 待复核 → 已启用 / 失败 */
export type StructureStatus = 'pending' | 'structuring' | 'review' | 'ready' | 'failed'

export interface TemplateOut {
  id: number
  name: string
  category: string | null
  file_name: string | null
  file_size: number
  variables: string[]
  fields: TemplateField[]
  description: string | null
  uploader: string | null
  structure_status: StructureStatus
  version: number
  standardized: boolean
  created_at: string | null
  updated_at: string | null
}

/** 候选空位（扫描结果），复核页据此手动补字段 */
export interface TemplateCandidate {
  id: string
  anchor: string
  kind: string
  text: string
  context: string
  before: string
  after: string
  header: string
}

export interface TemplateDetail extends TemplateOut {
  outline: string
  candidates: TemplateCandidate[]
  meta: Record<string, unknown>
  error: string
}

export interface TemplatePage extends PageResult<TemplateOut> {
  categories: string[]
}

export interface ContractGenerateOut {
  record_id: number
  template_id: number
  template_name: string
  file_name: string
  download_url: string
  missing_variables: string[]
}

export interface ContractRecord {
  id: number
  template_id: number
  template_name: string
  file_name: string
  file_size: number
  missing_variables: string[]
  values: Record<string, string>
  created_by: string | null
  created_at: string | null
}

/** 模板库列表（含字段 schema 与类型词表） */
export function listTemplates(params: {
  category?: string
  status?: string
  page?: number
  page_size?: number
}) {
  return http.get<never, ApiResult<TemplatePage>>('/templates', { params })
}

/** 模板详情：含文档大纲、候选空位、识别留痕（复核页用） */
export function getTemplate(id: number) {
  return http.get<never, ApiResult<TemplateDetail>>(`/templates/${id}`)
}

/** 导入模板（.docx，含 {{ 变量 }} 或下划线等填空痕迹） */
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

export function updateTemplate(
  id: number,
  payload: { name?: string; category?: string; description?: string },
) {
  return http.patch<never, ApiResult<TemplateOut>>(`/templates/${id}`, payload)
}

export function deleteTemplate(id: number) {
  return http.delete<never, ApiResult<{ id: number }>>(`/templates/${id}`)
}

/** 识别待填字段：扫描 → Dify 应用六 → 回写标准化模板 → 自检（耗时较长） */
export function structureTemplate(id: number) {
  return http.post<never, ApiResult<{ status: StructureStatus; fields: TemplateField[] }>>(
    `/templates/${id}/structure`,
  )
}

/** 保存复核后的字段定义；enable=true 时模板变为可用 */
export function saveTemplateFields(
  id: number,
  payload: { fields: TemplateField[]; contract_type?: string; enable: boolean },
) {
  return http.post<never, ApiResult<{ status: StructureStatus; fields: TemplateField[] }>>(
    `/templates/${id}/fields`,
    payload,
  )
}

export function resetTemplateStructure(id: number) {
  return http.post<never, ApiResult<{ id: number; structure_status: StructureStatus }>>(
    `/templates/${id}/reset`,
  )
}

export function listCategories() {
  return http.get<never, ApiResult<{ items: string[] }>>('/templates/categories')
}

export function createCategory(name: string, sort_order = 0) {
  return http.post<never, ApiResult<{ id: number; name: string }>>('/templates/categories', {
    name,
    sort_order,
  })
}

export function seedCategories() {
  return http.post<never, ApiResult<{ created: number }>>('/templates/categories/seed')
}

/** 合同生成：按字段取值做 docxtpl 确定性填充（不调 LLM） */
export function generateContract(templateId: number, variables: Record<string, string>) {
  return http.post<never, ApiResult<ContractGenerateOut>>('/generate/contract', {
    template_id: templateId,
    variables,
  })
}

/** 按当前取值渲染草稿预览（不落生成记录，内容哈希去重，可反复调用） */
export function previewContractDraft(templateId: number, variables: Record<string, string>) {
  return http.post<
    never,
    ApiResult<{ preview_id: string; dpi: number; page_count: number; pages: unknown[] }>
  >('/generate/contract/preview', { template_id: templateId, variables })
}

/** 合同生成历史（普通用户仅自己的记录） */
export function listContractRecords(params: { page?: number; page_size?: number } = {}) {
  return http.get<never, ApiResult<PageResult<ContractRecord>>>('/generate/contract/records', {
    params,
  })
}

export function deleteContractRecord(recordId: number) {
  return http.delete<never, ApiResult<{ id: number }>>(
    `/generate/contract/records/${recordId}`,
  )
}
