import http from './http'

export interface ChatRequest {
  query: string
  conversation_id?: string
  inputs?: Record<string, unknown>
}

export function chatBlocking(data: ChatRequest) {
  return http.post('/chat', data)
}

// SSE 流式对话：用 fetch 读取后端 text/event-stream
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
    // 按 SSE 事件边界切分
    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''
    for (const raw of events) {
      const eventLine = raw.split('\n').find((l) => l.startsWith('event:'))
      const dataLine = raw.split('\n').find((l) => l.startsWith('data:'))
      if (!dataLine) continue
      const event = eventLine ? eventLine.slice('event:'.length).trim() : 'message'
      try {
        onEvent(event, JSON.parse(dataLine.slice('data:'.length).trim()))
      } catch {
        onEvent(event, { raw: dataLine.slice('data:'.length).trim() })
      }
    }
  }
}
