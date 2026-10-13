import http from './http'
import type { ApiResult } from './http'
import type { PageResult } from './knowledge'

export interface Violation {
  law_name: string
  article: string
  description: string
  link?: string | null
}

export interface ReferenceCase {
  case_name: string
  lesson: string
}

export interface Citation {
  document_name: string
  section: string
  url: string
}

export interface RiskItem {
  clause: string
  risk_level: 'high' | 'medium' | 'low' | string
  violations: Violation[]
  analysis?: string
  citations?: Citation[]
  case_analysis?: string
  needs_review?: boolean
  validation_notes?: string[]
  reference_case: ReferenceCase | null
  suggestion: string
  chunk_index?: number | null
  location?: string | null
}

export interface ReviewResult {
  is_compliant: boolean
  summary: string
  total_chunks: number
  failed_chunks: number
  failed_details?: { chunk_index: number; location: string; error: string }[]
  risks: RiskItem[]
}

export interface ReviewTaskOut {
  id: number
  review_type: 'contract' | 'regulation' | string
  input_type: 'text' | 'file' | string
  source_name: string | null
  status: 'pending' | 'running' | 'completed' | 'failed' | string
  total_chunks: number
  completed_chunks: number
  failed_chunks: number
  is_compliant: boolean | null
  error: string | null
  created_at: string | null
  updated_at: string | null
  result: ReviewResult | null
  progress: {
    stage: 'upload' | 'parse' | 'review' | 'done'
    processed_chunks: number
    active_chunks: { index: number; phase: 'retrieval' | 'generation' }[]
  } | null
}

/** 提交审查任务：仅支持文件上传，返回 task_id 供轮询 */
export function submitReview(params: {
  reviewType: 'contract' | 'regulation'
  file: File
}) {
  const form = new FormData()
  form.append('review_type', params.reviewType)
  form.append('file', params.file)
  return http.post<never, ApiResult<{ task_id: number; status: string }>>('/review', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function getReviewTask(taskId: number) {
  return http.get<never, ApiResult<ReviewTaskOut>>(`/review/${taskId}`)
}

export function listReviewTasks(params: {
  review_type?: string
  page?: number
  page_size?: number
}) {
  return http.get<never, ApiResult<PageResult<ReviewTaskOut>>>('/review/tasks', { params })
}

export function deleteReviewTask(taskId: number) {
  return http.delete<never, ApiResult<{ id: number }>>(`/review/${taskId}`)
}
