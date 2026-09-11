import { defineStore } from 'pinia'
import { ref } from 'vue'

interface UserInfo {
  username: string
  role: string
}

export const useUserStore = defineStore('user', () => {
  const token = ref(localStorage.getItem('token') || '')
  const userInfo = ref<UserInfo | null>(null)

  function setToken(value: string) {
    token.value = value
    localStorage.setItem('token', value)
  }

  function logout() {
    token.value = ''
    userInfo.value = null
    localStorage.removeItem('token')
  }

  return { token, userInfo, setToken, logout }
})
