import http from './http'

export interface ChatRequest {
  query: string
  conversation_id?: string
  inputs?: Record<string, unknown>
}

export interface ChatAnswer {
  answer: string
  conversation_id: string
  sources: unknown[]
}

export function chatBlocking(data: ChatRequest) {
  return http.post<never, ChatAnswer>('/chat', data)
}

/**
 * SSE 流式对话：用 fetch 读取后端 text/event-stream。
 *
 * 注意：sse-starlette 的事件分隔符是 CRLF（`\r\n\r\n`），不是 `\n\n`——
 * 按 `\n\n` 切分会一条事件都解析不出来，因此这里用 `/\r?\n\r?\n/` 兼容两种换行。
 */
export async function chatStream(
  data: ChatRequest,
  onEvent: (event: string, payload: Record<string, unknown>) => void,
) {
  const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const token = localStorage.getItem('token') || ''
  const response = await fetch(`${baseURL}/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(data),
  })
  if (!response.ok) {
    throw new Error(`对话请求失败（HTTP ${response.status}）`)
  }
  if (!response.body) {
    throw new Error('浏览器不支持流式响应')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const events = buffer.split(/\r?\n\r?\n/)
    buffer = events.pop() ?? ''
    for (const raw of events) {
      const lines = raw.split(/\r?\n/)
      const eventLine = lines.find((l) => l.startsWith('event:'))
      // 一个事件可能有多行 data（SSE 规范），需要按行拼接
      const dataLines = lines.filter((l) => l.startsWith('data:'))
      if (!dataLines.length) continue

      const event = eventLine ? eventLine.slice('event:'.length).trim() : 'message'
      const payloadText = dataLines.map((l) => l.slice('data:'.length).trim()).join('\n')
      try {
        onEvent(event, JSON.parse(payloadText))
      } catch {
        onEvent(event, { raw: payloadText })
      }
    }
  }
}
