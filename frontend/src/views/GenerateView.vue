<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { generateDoc } from '@/api/generate'

const outline = ref('')
const loading = ref(false)

async function onSubmit() {
  if (!outline.value.trim()) {
    ElMessage.warning('请输入大纲或要点')
    return
  }
  loading.value = true
  try {
    await generateDoc({ outline: outline.value })
    ElMessage.success('生成任务已提交')
  } catch {
    ElMessage.error('生成失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page">
    <el-card header="合同 / 规章制度生成">
      <el-input
        v-model="outline"
        type="textarea"
        :rows="10"
        placeholder="输入大纲或要点，系统生成文档内容"
      />
      <el-button class="mt" type="primary" :loading="loading" @click="onSubmit">
        生成文档
      </el-button>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  padding: 16px;
}
.mt {
  margin-top: 12px;
}
</style>
