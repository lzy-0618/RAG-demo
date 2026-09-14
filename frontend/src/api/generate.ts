import http from './http'
import type { ApiResult } from './http'
import type { PageResult } from './knowledge'

export interface RiskItem {
  clause: string
  risk_level: string
  violations: Array<{ law_name: string; article: string; description: string }>
  suggestion: string
  location?: string | null
}

export interface GenerationTaskOut {
  id: number
  status: 'pending' | 'running' | 'completed' | 'failed' | string
  round: number
  max_rounds: number
  review_round: number
  total_chunks: number
  completed_chunks: number
  failed_chunks: number
  is_compliant: boolean | null
  summary: string | null
  requirement: string
  outline: string | null
  sections: Array<{ title: string; content: string }>
  review: { summary: string; risks: RiskItem[] } | null
  doc_name: string | null
  download_url: string | null
  error: string | null
  created_at: string | null
}

/** 第一段：按需求生成大纲（同步返回，可编辑确认） */
export function generateRegulationOutline(requirement: string) {
  return http.post<never, ApiResult<{ requirement: string; outline_text: string }>>(
    '/generate/regulation/outline',
    { requirement },
  )
}

/** 第二段：按确认后的大纲生成全文，并自动合规审查（不合规自动修正，最多 3 轮） */
export function generateRegulationDocument(requirement: string, outline: string) {
  return http.post<never, ApiResult<{ task_id: number; status: string }>>(
    '/generate/regulation/document',
    { requirement, outline },
  )
}

export function getRegulationTask(taskId: number) {
  return http.get<never, ApiResult<GenerationTaskOut>>(`/generate/regulation/${taskId}`)
}

export function listRegulationTasks(params: { page?: number; page_size?: number }) {
  return http.get<never, ApiResult<PageResult<GenerationTaskOut>>>('/generate/regulation', {
    params,
  })
}

export function deleteRegulationTask(taskId: number) {
  return http.delete<never, ApiResult<{ id: number }>>(`/generate/regulation/${taskId}`)
}
