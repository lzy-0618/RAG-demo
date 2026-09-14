<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()

// 开发环境展示种子账号（生产构建不包含该常量，凭后端 .env 配置）
const isDev = import.meta.env.DEV
const DEMO_ACCOUNTS = [
  { label: '专家（可纠错标注）', username: 'expert', password: 'Expert@2026' },
  { label: '普通用户', username: 'user01', password: 'User@2026' },
]

const form = ref({ username: '', password: '' })
const loading = ref(false)

function useAccount(username: string, password: string) {
  form.value = { username, password }
}

async function onSubmit() {
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请输入账号与密码')
    return
  }
  loading.value = true
  try {
    await userStore.login(form.value.username, form.value.password)
    ElMessage.success('登录成功')
    router.push('/chat')
  } catch {
    // 错误提示由 http 拦截器统一处理
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <el-card class="login-card">
      <template #header>
        <div class="title">企业合规智能平台</div>
      </template>
      <el-form label-position="top" @submit.prevent="onSubmit">
        <el-form-item label="账号">
          <el-input v-model="form.username" placeholder="请输入账号" @keyup.enter="onSubmit" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            placeholder="请输入密码"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-button type="primary" class="submit" :loading="loading" @click="onSubmit">
          登录
        </el-button>
      </el-form>

      <div v-if="isDev" class="demo">
        <div class="demo-title">开发环境种子账号（点击填入）</div>
        <div v-for="acc in DEMO_ACCOUNTS" :key="acc.username" class="demo-item">
          <el-button link type="primary" size="small" @click="useAccount(acc.username, acc.password)">
            {{ acc.label }}：{{ acc.username }} / {{ acc.password }}
          </el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
}
.login-card {
  width: 380px;
}
.title {
  text-align: center;
  font-weight: 600;
  font-size: 18px;
}
.submit {
  width: 100%;
}
.demo {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px dashed #ebeef5;
  font-size: 12px;
  color: #909399;
}
.demo-title {
  margin-bottom: 4px;
}
.demo-item {
  line-height: 1.8;
}
</style>
