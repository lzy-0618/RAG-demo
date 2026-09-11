import http from './http'

export function reviewContract(content: string, reviewType = 'contract') {
  return http.post('/review/contract', { content, review_type: reviewType })
}

export function generateDoc(payload: {
  template_name?: string
  outline?: string
  variables?: Record<string, unknown>
}) {
  return http.post('/generate', payload)
}

export function listTemplates() {
  return http.get('/templates')
}
