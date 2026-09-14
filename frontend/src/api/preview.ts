/** 文档预览：后端把 docx 转 PDF 并光栅化成 PNG，前端只负责展示。
 *
 * 不用前端 pdf.js 渲染：pdf.js 处理 LibreOffice 导出的中文 CID 子集时字形会错位
 * （汉字被渲染成 `! " # $` 之类的 ASCII 字形），而 MuPDF 渲染同一份 PDF 是正确的。
 */
import http from './http'
import type { ApiResult } from './http'

export interface PreviewPage {
  page: number
  width: number
  height: number
}

export interface PreviewMeta {
  dpi: number
  page_count: number
  pages: PreviewPage[]
}

/** 预览元信息（页数 + 每页尺寸，单位 pt） */
export function fetchPreviewMeta(path: string) {
  return http.get<never, ApiResult<PreviewMeta>>(path)
}

/** 拉取单页图片，返回可直接用于 <img> 的对象 URL（调用方负责 revokeObjectURL） */
export async function fetchPreviewImage(path: string): Promise<string> {
  const blob = await http.get<never, Blob>(path, { responseType: 'blob' })
  return URL.createObjectURL(blob)
}
