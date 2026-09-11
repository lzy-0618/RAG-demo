<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

const original = ref('')
const corrected = ref('')

function onSubmit() {
  if (!original.value.trim()) {
    ElMessage.warning('请输入待纠错内容')
    return
  }
  // TODO: 调用纠错接口，人工确认后回写知识库
  ElMessage.info('纠错提交功能待实现（需求 ⑤）')
}
</script>

<template>
  <div class="page">
    <el-card header="内容纠错">
      <el-input
        v-model="original"
        type="textarea"
        :rows="6"
        placeholder="原始内容"
      />
      <el-input
        v-model="corrected"
        class="mt"
        type="textarea"
        :rows="6"
        placeholder="纠错后的内容"
      />
      <el-button class="mt" type="primary" @click="onSubmit">提交纠错</el-button>
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
