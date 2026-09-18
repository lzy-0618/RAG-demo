/// <reference types="vite/client" />

/** .env.android 提供 App 构建的值；npm run dev 走 .env（不存在时用下面的可选语义） */
interface ImportMetaEnv {
  /** 后端 API 基地址。模拟器用 http://10.0.2.2:8000/api/v1，真机换局域网 IP */
  readonly VITE_API_BASE_URL?: string
  /** 设为 'false' 关闭登录页的演示账号区域（默认展示） */
  readonly VITE_SHOW_DEMO_ACCOUNTS?: string
}
