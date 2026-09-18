<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BrandMark from '@/components/BrandMark.vue'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

// 登录页不套后台布局
const isPublicPage = computed(() => Boolean(route.meta.public))

function onLogout() {
  userStore.logout()
  router.push('/login')
}
</script>

<template>
  <router-view v-if="isPublicPage" />

  <div v-else class="layout">
    <header class="header">
      <div class="head-main">
        <BrandMark layout="seal" :size="26" />
        <h1 class="head-title">{{ route.meta.title }}</h1>
      </div>
      <div class="user">
        <span v-if="userStore.username" class="user-name">{{ userStore.username }}</span>
        <el-tag v-if="userStore.isExpert" type="warning" size="small">专家</el-tag>
        <el-tag v-else-if="userStore.username" type="info" size="small">普通用户</el-tag>
        <button type="button" class="logout" @click="onLogout">
          <AppIcon name="logout" :size="16" />
          <span>退出</span>
        </button>
      </div>
    </header>

    <main class="main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh;
  /* 刘海屏 / 手势条留白。dvh 让 WebView 在软键盘弹起时收缩，避免底部输入区被遮挡。 */
  padding: env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom)
    env(safe-area-inset-left);
  overflow: hidden;
  color: var(--ink);
  /* 氛围层：纸面暖光，替代原来的纯平灰底。
     外壳不滚动，两个超大径向渐变只绘制一次，没有滚动重绘开销。 */
  background-image: radial-gradient(
      64rem 44rem at 6% -14%,
      rgba(179, 52, 42, 0.07),
      rgba(179, 52, 42, 0) 62%
    ),
    radial-gradient(56rem 42rem at 102% 2%, rgba(138, 90, 18, 0.06), rgba(138, 90, 18, 0) 58%);
}

/* ---------- 文书头 ---------- */
.header {
  position: relative;
  z-index: 1;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--rule-strong);
  background: rgba(255, 255, 255, 0.72);
}

/* 文书头双线：顶栏下沿 3px 处再压一条发丝线 */
.header::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: -3px;
  height: 1px;
  background: var(--rule);
}

.head-main {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.head-title {
  margin: 0;
  font-family: var(--font-serif);
  font-size: var(--fs-2xl);
  font-weight: 600;
  letter-spacing: var(--tracking-display);
  line-height: 1.15;
  color: var(--ink);
  white-space: nowrap;
}

.user {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* 屏窄放不下侧栏，用户名改在抬头右侧呈现 */
.user-name {
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  letter-spacing: 0.06em;
  color: var(--muted);
}

/* 退出降为墨色次级动作：朱红留给登录与发送，全屏只留一个强调色 */
.logout {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  height: 32px;
  padding: 0 var(--space-2);
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: var(--fs-2xs);
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.logout:active {
  background: var(--surface-2);
  color: var(--ink);
}

.main {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

@media (max-width: 640px) {
  .head-title {
    font-size: var(--fs-xl);
    white-space: normal;
  }
}
</style>
