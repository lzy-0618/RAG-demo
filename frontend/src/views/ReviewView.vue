<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { reviewContract } from '@/api/generate'

const content = ref('')
const result = ref('')
const loading = ref(false)

async function onSubmit() {
  if (!content.value.trim()) {
    ElMessage.warning('请输入待审查的合同内容')
    return
  }
  loading.value = true
  try {
    const res = (await reviewContract(content.value)) as unknown as { data: unknown }
    result.value = JSON.stringify(res.data, null, 2)
  } catch {
    ElMessage.error('审查失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page">
    <el-card header="合同审查">
      <el-input
        v-model="content"
        type="textarea"
        :rows="10"
        placeholder="粘贴合同文本，系统将进行合规审查"
      />
      <el-button class="mt" type="primary" :loading="loading" @click="onSubmit">
        开始审查
      </el-button>
      <pre v-if="result" class="result">{{ result }}</pre>
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
.result {
  margin-top: 12px;
  padding: 12px;
  background: #f7f8fa;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
