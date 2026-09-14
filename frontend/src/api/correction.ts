import http from './http'
import type { ApiResult } from './http'
import type { PageResult } from './knowledge'

export interface CorrectionOut {
  id: number
  question: string | null
  source_content: string
  corrected_content: string
  expert: string | null
  chat_conversation_id: string | null
  chat_message_id: string | null
  dataset_id: string | null
  document_id: string | null
  local_document_id: number | null
  write_status: 'pending' | 'written' | 'failed' | string
  error: string | null
  created_at: string | null
}

export interface CorrectionCreate {
  source_content: string
  corrected_content: string
  question?: string | null
  conversation_id?: string | null
  message_id?: string | null
}

/** 提交专家标注（仅 expert 角色；普通用户返回 403） */
export function createCorrection(data: CorrectionCreate) {
  return http.post<never, ApiResult<CorrectionOut>>('/corrections', data)
}

export function listCorrections(params: { message_id?: string; expert?: string; page?: number; page_size?: number }) {
  return http.get<never, ApiResult<PageResult<CorrectionOut>>>('/corrections', { params })
}

/** 写库失败后重试 */
export function retryCorrection(id: number) {
  return http.post<never, ApiResult<CorrectionOut>>(`/corrections/${id}/retry`)
}

export function deleteCorrection(id: number) {
  return http.delete<never, ApiResult<{ id: number }>>(`/corrections/${id}`)
}
