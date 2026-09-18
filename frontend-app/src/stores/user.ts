import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { login as loginApi } from '@/api/auth'

interface UserInfo {
  username: string
  role: string
}

export const useUserStore = defineStore('user', () => {
  const token = ref(localStorage.getItem('token') || '')
  const username = ref(localStorage.getItem('username') || '')
  const role = ref(localStorage.getItem('role') || 'user')
  const userInfo = ref<UserInfo | null>(
    username.value ? { username: username.value, role: role.value } : null,
  )

  const isLoggedIn = computed(() => Boolean(token.value))
  /** 专家角色：可对 AI 回答做纠错标注（需求⑤） */
  const isExpert = computed(() => role.value === 'expert')

  async function login(user: string, password: string) {
    const data = await loginApi({ username: user, password })
    token.value = data.access_token
    username.value = data.username || user
    role.value = data.role || 'user'
    userInfo.value = { username: username.value, role: role.value }
    localStorage.setItem('token', data.access_token)
    localStorage.setItem('username', username.value)
    localStorage.setItem('role', role.value)
  }

  function logout() {
    token.value = ''
    username.value = ''
    role.value = 'user'
    userInfo.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('username')
    localStorage.removeItem('role')
  }

  return { token, username, role, userInfo, isLoggedIn, isExpert, login, logout }
})
