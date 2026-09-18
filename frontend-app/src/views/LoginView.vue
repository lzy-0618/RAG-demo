<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppIcon from '@/components/AppIcon.vue'
import BrandMark from '@/components/BrandMark.vue'
import { useUserStore } from '@/stores/user'

interface DemoAccount {
  role: string
  username: string
  password: string
}

const router = useRouter()
const userStore = useUserStore()

/**
 * 演示账号。**显式开启**：只有 .env.android 里写了 true 才展示，未设或设成别的值一律不展示。
 * 用 !== 'false' 那种"默认开启"的写法很危险——谁忘了在发版环境里设这个变量，凭据就会跟着出厂。
 * 凭据以后端 .env 的 SEED_* 为准。
 */
const DEMO_ACCOUNTS: DemoAccount[] = [
  { role: '普通用户', username: 'user01', password: 'User@2026' },
  { role: '专家用户', username: 'expert', password: 'Expert@2026' },
]
const showDemo = import.meta.env.VITE_SHOW_DEMO_ACCOUNTS === 'true'

const form = ref({ username: '', password: '' })
const loading = ref(false)
const copiedUser = ref('')
let copyTimer = 0

function useAccount(acc: DemoAccount) {
  form.value = { username: acc.username, password: acc.password }
}

/** clipboard API 在 WebView 里可能因权限缺失抛错，回退到临时 textarea 方案 */
async function copyText(text: string) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 落到下面的兜底实现
  }
  try {
    const el = document.createElement('textarea')
    el.value = text
    el.setAttribute('readonly', '')
    el.style.position = 'fixed'
    el.style.top = '-1000px'
    el.style.opacity = '0'
    document.body.appendChild(el)
    el.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(el)
    return ok
  } catch {
    return false
  }
}

async function copyAccount(acc: DemoAccount) {
  const ok = await copyText(`${acc.username} / ${acc.password}`)
  if (!ok) {
    ElMessage.warning('复制失败，请手动记下账号密码')
    return
  }
  copiedUser.value = acc.username
  window.clearTimeout(copyTimer)
  copyTimer = window.setTimeout(() => {
    copiedUser.value = ''
  }, 1500)
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

onBeforeUnmount(() => window.clearTimeout(copyTimer))
</script>

<template>
  <div class="login-page">
    <div class="login-inner reveal-group">
      <header class="brand-head">
        <BrandMark layout="stacked" :size="60" />
      </header>

      <el-form class="login-form" label-position="top" @submit.prevent="onSubmit">
        <el-form-item label="账号">
          <el-input v-model="form.username" placeholder="请输入账号" @keyup.enter="onSubmit">
            <template #prefix><AppIcon name="account" :size="18" /></template>
          </el-input>
        </el-form-item>

        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            placeholder="请输入密码"
            @keyup.enter="onSubmit"
          >
            <template #prefix><AppIcon name="lock" :size="18" /></template>
          </el-input>
        </el-form-item>

        <el-button type="primary" class="submit" :loading="loading" @click="onSubmit">
          登录
        </el-button>
      </el-form>

      <section v-if="showDemo" class="demo">
        <p class="demo-title u-caption">演示账号 · 点按填充，或复制</p>
        <div
          v-for="acc in DEMO_ACCOUNTS"
          :key="acc.username"
          class="demo-card"
          :class="{ 'is-copied': copiedUser === acc.username }"
        >
          <button type="button" class="demo-fill" @click="useAccount(acc)">
            <span class="demo-role">{{ acc.role }}</span>
            <span class="demo-cred u-num">{{ acc.username }} · {{ acc.password }}</span>
          </button>
          <button
            type="button"
            class="demo-copy"
            :aria-label="`复制${acc.role}账号密码`"
            @click="copyAccount(acc)"
          >
            <AppIcon :name="copiedUser === acc.username ? 'check' : 'copy'" :size="16" />
            <span>{{ copiedUser === acc.username ? '已复制' : '复制' }}</span>
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  /* 软键盘弹起时视口会被压到 400px 上下，页面必须可滚，否则登录按钮会被裁掉 */
  overflow-y: auto;
  min-height: 100vh;
  min-height: 100dvh;
  /* 登录页不在 App.vue 外壳内，安全区留白需自理 */
  padding: calc(env(safe-area-inset-top) + var(--space-6)) var(--space-5)
    calc(env(safe-area-inset-bottom) + var(--space-7));
  color: var(--ink);
  /* 纸面暖光：原来这里铺的是纯白面板，把 body 的纸色和纸纹整个盖住了 */
  background-image: radial-gradient(
      40rem 28rem at 10% -8%,
      rgba(179, 52, 42, 0.09),
      rgba(179, 52, 42, 0) 62%
    ),
    radial-gradient(36rem 26rem at 100% 6%, rgba(138, 90, 18, 0.07), rgba(138, 90, 18, 0) 58%);
}

/* margin:auto 而非 justify-content:center——后者在内容超出容器时会裁掉顶部 */
.login-inner {
  width: 100%;
  max-width: 420px;
  margin: auto;
}

.brand-head {
  display: flex;
  justify-content: center;
  padding-bottom: var(--space-5);
  /* 文书头双线：主分隔线下 3px 处再压一条发丝线 */
  border-bottom: 1px solid var(--rule-strong);
  position: relative;
}

.brand-head::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: -3px;
  height: 1px;
  background: var(--rule);
}

.login-form {
  margin-top: var(--space-5);
}

/* 48px 触控高度、16px 字号（低于 16px 会触发 Android 聚焦自动缩放） */
.login-form :deep(.el-form-item__label) {
  padding-bottom: var(--space-1);
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  letter-spacing: 0.14em;
  color: var(--muted);
}

.login-form :deep(.el-input__wrapper) {
  min-height: 48px;
  padding: 0 var(--space-4);
  border-radius: var(--radius-lg);
}

.login-form :deep(.el-input__inner) {
  font-size: 16px;
}

.login-form :deep(.el-input__prefix) {
  color: var(--muted);
  margin-right: var(--space-1);
}

.login-form :deep(.el-input__wrapper.is-focus .el-input__prefix) {
  color: var(--accent);
}

.submit {
  width: 100%;
  height: 48px;
  margin-top: var(--space-3);
  border-radius: var(--radius-lg);
  font-size: var(--fs-md);
  letter-spacing: 0.24em;
  text-indent: 0.24em;
}

/* ---------- 演示账号 ---------- */
.demo {
  margin-top: var(--space-6);
  padding-top: var(--space-4);
  border-top: 1px dashed var(--rule-strong);
}

.demo-title {
  margin: 0 0 var(--space-3);
  text-align: center;
}

.demo-card {
  display: flex;
  align-items: stretch;
  gap: var(--space-1);
  margin-bottom: var(--space-2);
  border: 1px solid var(--rule);
  border-radius: var(--radius-lg);
  background: var(--surface);
  overflow: hidden;
  transition: border-color var(--dur-fast) var(--ease-out);
}

.demo-card.is-copied {
  border-color: var(--ok);
}

/* 两个兄弟按钮而非嵌套——button 里不能再放 button */
.demo-fill {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-3) var(--space-4);
  border: 0;
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.demo-fill:active {
  background: var(--accent-wash);
}

.demo-role {
  font-size: var(--fs-xs);
  color: var(--ink-2);
}

.demo-cred {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.demo-copy {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-4);
  border: 0;
  border-left: 1px solid var(--rule);
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: var(--fs-2xs);
  cursor: pointer;
  transition: color var(--dur-fast) var(--ease-out);
}

.demo-copy:active {
  background: var(--surface-2);
  color: var(--accent);
}

.demo-card.is-copied .demo-copy {
  color: var(--ok);
}
</style>
