<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import NavIcon from '@/components/NavIcon.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

// 登录页不套后台布局
const isPublicPage = computed(() => Boolean(route.meta.public))

/** 侧栏是「卷宗目录」：图标说明条目性质，名称说明内容。
 *  当前项由 router-link 自动标注的 router-link-active 决定。 */
const NAV = [
  { path: '/chat', icon: 'chat', label: '智能问答' },
  { path: '/review', icon: 'contract-review', label: '合同审查' },
  { path: '/review/regulation', icon: 'regulation-review', label: '规章制度审查' },
  { path: '/knowledge', icon: 'knowledge', label: '知识库管理' },
  { path: '/templates', icon: 'template', label: '合同模板库管理' },
  { path: '/generate/contract', icon: 'contract-generate', label: '合同生成' },
  { path: '/generate/regulation', icon: 'regulation-generate', label: '规章制度生成' },
]

function onLogout() {
  userStore.logout()
  router.push('/login')
}
</script>

<template>
  <router-view v-if="isPublicPage" />

  <div v-else class="layout">
    <aside class="aside">
      <router-link to="/chat" class="brand">
        <span class="brand-mark" aria-hidden="true">审</span>
        <span class="brand-text">
          <span class="brand-title">宝智审</span>
          <span class="brand-sub">Compliance Intelligence</span>
        </span>
      </router-link>

      <nav class="nav" aria-label="主导航">
        <p class="nav-caption">目录 / Contents</p>
        <ul class="nav-list">
          <li v-for="item in NAV" :key="item.path">
            <router-link :to="item.path" class="nav-item">
              <NavIcon :name="item.icon" class="nav-icon" />
              <span class="nav-label">{{ item.label }}</span>
            </router-link>
          </li>
        </ul>
      </nav>

      <div class="aside-foot">
        <span class="foot-role">{{ userStore.isExpert ? '专家' : '用户' }}</span>
        <span class="foot-name">{{ userStore.username || '未登录' }}</span>
      </div>
    </aside>

    <div class="body">
      <header class="header">
        <div class="head-main">
          <h1 class="head-title">{{ route.meta.title }}</h1>
        </div>
        <div class="user">
          <el-tag v-if="userStore.isExpert" type="warning" size="small">专家</el-tag>
          <el-tag v-else-if="userStore.username" type="info" size="small">普通用户</el-tag>
          <el-button link type="primary" @click="onLogout">退出</el-button>
        </div>
      </header>

      <main class="main">
        <router-view />
      </main>
    </div>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  /* dvh 让 WebView 在软键盘弹起时收缩，避免底部输入区被遮挡；旧内核回退到 vh */
  height: 100vh;
  height: 100dvh;
  /* 刘海屏 / 手势条留白。桌面浏览器下 env() 取值为 0，无副作用 */
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

/* ---------- 侧栏：卷宗目录 ---------- */
.aside {
  flex: none;
  width: 248px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: linear-gradient(180deg, #fffefc 0%, #fbf8f4 100%);
  border-right: 1px solid var(--rule);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-5) var(--space-5) var(--space-4);
  color: inherit;
  text-decoration: none;
}

.brand:hover {
  text-decoration: none;
}

/* 印记：朱红方章 + 内描边，与 favicon 同一枚记号 */
.brand-mark {
  flex: none;
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: var(--on-accent);
  font-family: var(--font-serif);
  font-size: 21px;
  font-weight: 600;
  line-height: 1;
  box-shadow: inset 0 0 0 1px rgba(253, 251, 249, 0.4);
}

.brand-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.brand-title {
  font-family: var(--font-serif);
  font-size: var(--fs-md);
  font-weight: 600;
  letter-spacing: var(--tracking-display);
  line-height: 1.35;
  color: var(--ink);
  white-space: nowrap;
}

.brand-sub {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
}

.nav {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-2) var(--space-3) var(--space-4);
}

.nav-caption {
  margin: 0 0 var(--space-2);
  padding: 0 var(--space-2) var(--space-2);
  border-bottom: 1px solid var(--rule);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--muted);
}

.nav-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: 44px;
  padding: var(--space-2) var(--space-2) var(--space-2) var(--space-4);
  border-radius: var(--radius-sm);
  color: var(--ink-2);
  text-decoration: none;
  transition: color var(--dur-fast) var(--ease-out),
    background-color var(--dur-fast) var(--ease-out);
}

.nav-item:hover {
  text-decoration: none;
}

/* 朱红竖线是「当前定位」的唯一标记：默认宽度 0，悬停时擦入 */
.nav-item::before {
  content: "";
  position: absolute;
  left: 0;
  top: 50%;
  width: 0;
  height: 18px;
  transform: translateY(-50%);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  background: var(--accent);
  transition: width var(--dur-fast) var(--ease-out), height var(--dur-base) var(--ease-out);
}

.nav-item:hover {
  color: var(--ink);
  background: var(--surface-2);
}

.nav-item:hover::before {
  width: 3px;
}

.nav-item:hover .nav-label {
  letter-spacing: 0.02em;
}

.nav-icon {
  flex: none;
  color: var(--muted);
  transition: color var(--dur-fast) var(--ease-out);
}

.nav-label {
  font-size: var(--fs-base);
  transition: letter-spacing var(--dur-fast) var(--ease-out);
}

.nav-item.router-link-active {
  color: var(--ink);
  font-weight: 600;
  background: var(--accent-wash);
}

.nav-item.router-link-active::before {
  width: 3px;
  height: 26px;
}

.nav-item.router-link-active .nav-icon {
  color: var(--accent);
}

.aside-foot {
  flex: none;
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-5) var(--space-4);
  border-top: 1px solid var(--rule);
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  letter-spacing: 0.06em;
}

.foot-role {
  color: var(--accent);
}

.foot-name {
  color: var(--muted);
}

/* ---------- 主区：文书头 ---------- */
.body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.header {
  position: relative;
  z-index: 1;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-5);
  padding: var(--space-4) var(--space-6);
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
  align-items: baseline;
  gap: var(--space-4);
  min-width: 0;
}

.head-title {
  margin: 0;
  font-family: var(--font-serif);
  font-size: var(--fs-3xl);
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
  gap: var(--space-3);
}

.main {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* 窄屏：侧栏收成编号索引，标题回落，保证不溢出。
   完整的移动端方案（表格卡片化等）留在后续阶段。 */
@media (max-width: 1024px) {
  .aside {
    width: 68px;
  }

  .brand {
    justify-content: center;
    padding: var(--space-4) 0;
  }

  /* 收起文字但保留给读屏。这里必须用视觉隐藏而不是 display:none ——
     否则品牌链接与只剩图标的导航项都会失去可访问名称。 */
  .brand-text,
  .nav-label {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
    border: 0;
  }

  .nav-caption,
  .foot-name {
    display: none;
  }

  .nav-item {
    justify-content: center;
    padding: var(--space-2) 0;
  }

  .aside-foot {
    justify-content: center;
    padding: var(--space-3) 0;
  }

  .head-title {
    font-size: var(--fs-2xl);
  }
}

@media (max-width: 640px) {
  .header {
    padding: var(--space-3) var(--space-4);
  }

  .head-title {
    font-size: var(--fs-xl);
    white-space: normal;
  }
}
</style>
