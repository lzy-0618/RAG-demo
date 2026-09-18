import axios from 'axios'
import type { AxiosInstance, InternalAxiosRequestConfig, AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'
import { navigateTo } from '@/utils/navigation'

/** 后端统一响应结构：{ code, message, data }，code=0 表示成功 */
export interface ApiResult<T = unknown> {
  code: number
  message: string
  data: T
}

const http: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  // 审查 / 生成链路含多轮 LLM 调用，超时给足
  timeout: 300000,
})

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response: AxiosResponse) => response.data,
  (error) => {
    const status = error?.response?.status
    const payload = error?.response?.data
    // 后端业务异常为 { code, message }，优先展示 message
    const raw = payload?.message || payload?.detail || error.message || '请求失败'
    const message = typeof raw === 'string' ? raw : '请求失败'

    if (status === 401) {
      localStorage.removeItem('token')
      if (!window.location.pathname.startsWith('/login')) {
        ElMessage.warning('登录已过期，请重新登录')
        // 走 router 而非整页跳转：WebView 内整页重载会丢状态并闪白屏
        navigateTo('/login')
      }
    } else {
      ElMessage.error(message)
    }
    return Promise.reject(error)
  },
)

export default http
