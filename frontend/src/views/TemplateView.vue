<script setup lang="ts">
import { ref } from 'vue'
import { listTemplates } from '@/api/generate'

const templates = ref<unknown[]>([])

async function load() {
  try {
    const res = (await listTemplates()) as unknown as { data: unknown[] }
    templates.value = res.data ?? []
  } catch {
    /* 骨架阶段忽略 */
  }
}

load()
</script>

<template>
  <div class="page">
    <el-card header="合同模板库">
      <el-table :data="templates" empty-text="暂无模板">
        <el-table-column prop="name" label="模板名称" />
        <el-table-column prop="category" label="分类" />
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  padding: 16px;
}
</style>
