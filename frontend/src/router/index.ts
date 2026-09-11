import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/chat' },
  {
    path: '/chat',
    name: 'chat',
    component: () => import('@/views/ChatView.vue'),
    meta: { title: '智能问答' },
  },
  {
    path: '/knowledge',
    name: 'knowledge',
    component: () => import('@/views/KnowledgeView.vue'),
    meta: { title: '知识库管理' },
  },
  {
    path: '/review',
    name: 'review',
    component: () => import('@/views/ReviewView.vue'),
    meta: { title: '合同审查' },
  },
  {
    path: '/generate',
    name: 'generate',
    component: () => import('@/views/GenerateView.vue'),
    meta: { title: '文档生成' },
  },
  {
    path: '/templates',
    name: 'templates',
    component: () => import('@/views/TemplateView.vue'),
    meta: { title: '合同模板库' },
  },
  {
    path: '/correct',
    name: 'correct',
    component: () => import('@/views/CorrectView.vue'),
    meta: { title: '内容纠错' },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

// TODO: 路由守卫：未登录跳转、按钮级权限（RBAC）
router.beforeEach((to, _from, next) => {
  document.title = `${to.meta.title ?? 'RAG_demo'} - 企业合规智能平台`
  next()
})

export default router
