<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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

  <el-container v-else class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">企业合规智能平台</div>
      <el-menu :default-active="route.path" router>
        <el-menu-item index="/chat">智能问答</el-menu-item>
        <el-menu-item index="/knowledge">知识库管理</el-menu-item>
        <el-menu-item index="/review">合同审查</el-menu-item>
        <el-menu-item index="/review/regulation">制度审查</el-menu-item>
        <el-menu-item index="/generate">文档生成</el-menu-item>
        <el-menu-item index="/templates">合同模板库</el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <span class="title">{{ route.meta.title }}</span>
        <div class="user">
          <span class="name">{{ userStore.username || '未登录' }}</span>
          <el-tag v-if="userStore.isExpert" type="warning" size="small">专家</el-tag>
          <el-tag v-else-if="userStore.username" type="info" size="small">普通用户</el-tag>
          <el-button link type="primary" @click="onLogout">退出</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout {
  height: 100vh;
}
.aside {
  border-right: 1px solid #eee;
}
.logo {
  height: 56px;
  line-height: 56px;
  text-align: center;
  font-weight: 600;
  border-bottom: 1px solid #eee;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #eee;
  height: 56px;
}
.title {
  font-weight: 600;
}
.user {
  display: flex;
  align-items: center;
  gap: 10px;
}
.user .name {
  color: #606266;
  font-size: 13px;
}
.main {
  padding: 0;
  overflow: hidden;
}
</style>
