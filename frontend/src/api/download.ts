/** 带鉴权的文件下载（产物、模板原文件等）。
 *
 * 浏览器直接 `<a href>` 无法带上 Authorization 头，所以统一走 fetch + blob。
 */

function baseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL || '/api/v1'
}

export async function fetchAuthedBlob(path: string): Promise<Blob> {
  const token = localStorage.getItem('token') || ''
  const resp = await fetch(`${baseUrl()}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!resp.ok) {
    let message = `下载失败（HTTP ${resp.status}）`
    try {
      const payload = (await resp.json()) as { message?: string }
      if (payload?.message) message = payload.message
    } catch {
      /* 非 JSON 响应体，保留默认提示 */
    }
    throw new Error(message)
  }
  return resp.blob()
}

/** 下载并触发浏览器保存。path 为后端 API 路径（含前导斜杠）。 */
export async function downloadAuthedFile(path: string, filename: string): Promise<void> {
  const blob = await fetchAuthedBlob(path)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
