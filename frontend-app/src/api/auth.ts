import http from './http'

export interface LoginPayload {
  username: string
  password: string
}

export interface TokenData {
  access_token: string
  token_type: string
  username: string
  role: string
}

/** 登录签发 JWT（后端校验密码哈希，角色随令牌返回） */
export function login(data: LoginPayload) {
  return http.post<never, TokenData>('/auth/login', data)
}
