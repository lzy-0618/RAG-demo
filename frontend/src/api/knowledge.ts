import http from './http'
import type { ApiResult } from './http'

export interface DatasetOut {
  key: string
  name: string
  dataset_id: string
  configured: boolean
  document_count: number
}

export interface DocumentOut {
  id: number
  title: string
  dataset_key: string
  doc_type: 'file' | 'text'
  status: 'uploaded' | 'parsing' | 'ready' | 'failed'
  dify_document_id: string | null
  uploader: string | null
  error: string | null
  created_at: string | null
  updated_at: string | null
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export function listDatasets() {
  return http.get<never, ApiResult<DatasetOut[]>>('/knowledge/datasets')
}

/** 把 Dify 中已存在但本地缺失的文档补录到本地表（历史文档可见） */
export function syncDataset(datasetKey: string) {
  return http.post<never, ApiResult<{ dataset_key: string; created: number }>>(
    `/knowledge/datasets/${datasetKey}/sync`,
  )
}

/** 文件入库：需指定知识库标识（law/regulation/case/rule/expert） */
export function uploadDocument(datasetKey: string, file: File) {
  const formData = new FormData()
  formData.append('dataset_key', datasetKey)
  formData.append('file', file)
  return http.post<never, ApiResult<DocumentOut>>('/knowledge/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function listDocuments(params: {
  dataset_key?: string
  page?: number
  page_size?: number
}) {
  return http.get<never, ApiResult<PageResult<DocumentOut>>>('/knowledge/documents', { params })
}

/** 刷新索引状态：Dify 索引是异步的，parsing 中的文档需轮询 */
export function refreshDocument(id: number) {
  return http.post<never, ApiResult<DocumentOut>>(`/knowledge/documents/${id}/refresh`)
}

export function deleteDocument(id: number) {
  return http.delete<never, ApiResult<{ id: number }>>(`/knowledge/documents/${id}`)
}
