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
    <section class="intro reveal-group">
      <span class="mark" aria-hidden="true">审</span>
      <h1 class="hero">宝智审</h1>
      <span class="rule" aria-hidden="true" />
      <p class="lede">
        制度、法规与审查依据收在同一处：问答、审查与生成共用同一套规范，答复可回溯到具体条款。
      </p>
      <p class="foot u-caption">内部系统 · 仅供授权人员使用</p>
    </section>

    <section class="panel">
      <div class="panel-inner reveal-group">
        <p class="panel-caption u-caption">登录 / Sign in</p>

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

        <div v-if="isDev" class="seeds">
          <p class="seeds-caption u-caption">开发环境种子账号</p>
          <button
            v-for="acc in DEMO_ACCOUNTS"
            :key="acc.username"
            type="button"
            class="seed"
            @click="useAccount(acc.username, acc.password)"
          >
            <span class="seed-role">{{ acc.label }}</span>
            <span class="seed-cred u-num">{{ acc.username }} / {{ acc.password }}</span>
          </button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.login-page {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(380px, 0.85fr);
  height: 100vh;
  color: var(--ink);
}

/* 左：定调面板。非对称 —— 大留白 + 衬线大标题 + 发丝规则线，
   替代原来「居中卡片压浅灰底」那套与任何后台都通用的构图。 */
.intro {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: var(--space-5);
  padding: var(--space-8) clamp(var(--space-6), 8vw, 120px);
  background-image: radial-gradient(
      52rem 40rem at 4% 6%,
      rgba(179, 52, 42, 0.09),
      rgba(179, 52, 42, 0) 60%
    ),
    radial-gradient(44rem 34rem at 92% 96%, rgba(138, 90, 18, 0.07), rgba(138, 90, 18, 0) 58%);
}

.mark {
  display: grid;
  place-items: center;
  width: 56px;
  height: 56px;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: var(--on-accent);
  font-family: var(--font-serif);
  font-size: var(--fs-3xl);
  font-weight: 600;
  line-height: 1;
  box-shadow: inset 0 0 0 1.5px rgba(253, 251, 249, 0.4);
}

/* 三个字一行，比原来的两行短语更能撑起这块留白 */
.hero {
  margin: 0;
  font-family: var(--font-serif);
  font-size: clamp(40px, 5.4vw, 68px);
  font-weight: 600;
  letter-spacing: var(--tracking-display);
  line-height: 1.05;
  color: var(--ink);
}

.rule {
  width: 72px;
  height: 3px;
  border-top: 1px solid var(--rule-strong);
  border-bottom: 1px solid var(--rule);
}

.lede {
  max-width: 34em;
  font-size: var(--fs-md);
  line-height: var(--lh-base);
  color: var(--ink-2);
}

.foot {
  margin-top: var(--space-3);
}

/* 右：登录面板 */
.panel {
  display: flex;
  align-items: center;
  border-left: 1px solid var(--rule);
  background: var(--surface);
}

.panel-inner {
  width: 100%;
  max-width: 380px;
  margin: 0 auto;
  padding: var(--space-8) var(--space-7);
}

.panel-caption {
  margin: 0 0 var(--space-5);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--rule);
}

.submit {
  width: 100%;
  margin-top: var(--space-2);
}

.seeds {
  margin-top: var(--space-6);
  padding-top: var(--space-4);
  border-top: 1px dashed var(--rule-strong);
}

.seeds-caption {
  margin: 0 0 var(--space-2);
}

/* 种子账号做成可点的凭据行，而不是一堆链接 */
.seed {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  margin-bottom: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--rule);
  border-radius: var(--radius-sm);
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease-out),
    background-color var(--dur-fast) var(--ease-out);
}

.seed:hover {
  border-color: var(--accent);
  background: var(--accent-wash);
}

.seed-role {
  font-size: var(--fs-xs);
  color: var(--ink-2);
}

.seed-cred {
  font-size: var(--fs-2xs);
  color: var(--muted);
}

@media (max-width: 900px) {
  .login-page {
    grid-template-columns: 1fr;
    height: auto;
    min-height: 100vh;
  }

  .intro {
    justify-content: flex-start;
    padding: var(--space-7) var(--space-5) var(--space-5);
  }

  .panel {
    border-left: none;
    border-top: 1px solid var(--rule);
  }

  .panel-inner {
    max-width: none;
    padding: var(--space-6) var(--space-5) var(--space-7);
  }
}
</style>
