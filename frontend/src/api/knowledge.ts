import http from './http'

export function uploadDocument(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return http.post('/knowledge/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function listDocuments() {
  return http.get('/knowledge/documents')
}
