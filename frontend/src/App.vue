<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">企业合规智能平台</div>
      <el-menu :default-active="route.path" router>
        <el-menu-item index="/chat">智能问答</el-menu-item>
        <el-menu-item index="/knowledge">知识库管理</el-menu-item>
        <el-menu-item index="/review">合同审查</el-menu-item>
        <el-menu-item index="/generate">文档生成</el-menu-item>
        <el-menu-item index="/templates">合同模板库</el-menu-item>
        <el-menu-item index="/correct">内容纠错</el-menu-item>
      </el-menu>
    </el-aside>
    <el-main class="main">
      <router-view />
    </el-main>
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
.main {
  padding: 0;
  overflow: hidden;
}
</style>
