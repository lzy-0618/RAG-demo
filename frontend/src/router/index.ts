import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/chat' },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', public: true },
  },
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
    path: '/review/regulation',
    name: 'regulationReview',
    component: () => import('@/views/RegulationReviewView.vue'),
    meta: { title: '制度审查' },
  },
  {
    path: '/generate/contract',
    name: 'contractGenerate',
    component: () => import('@/views/ContractGenerateView.vue'),
    meta: { title: '合同生成' },
  },
  {
    path: '/generate/regulation',
    name: 'regulationGenerate',
    component: () => import('@/views/RegulationGenerateView.vue'),
    meta: { title: '规章制度生成' },
  },
  {
    path: '/templates',
    name: 'templates',
    component: () => import('@/views/TemplateView.vue'),
    meta: { title: '合同模板库' },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

router.beforeEach((to, _from, next) => {
  document.title = `${to.meta.title ?? 'RAG_demo'} - 企业合规智能平台`
  const token = localStorage.getItem('token')
  if (!to.meta.public && !token) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }
  if (to.path === '/login' && token) {
    next('/chat')
    return
  }
  next()
})

export default router
