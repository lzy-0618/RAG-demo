<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { uploadDocument, listDocuments } from '@/api/knowledge'

const fileList = ref<File[]>([])
const uploading = ref(false)
const documents = ref<unknown[]>([])

async function onUpload() {
  if (fileList.value.length === 0) {
    ElMessage.warning('请先选择文件')
    return
  }
  uploading.value = true
  try {
    for (const file of fileList.value) {
      await uploadDocument(file)
    }
    ElMessage.success('上传成功，等待解析入库')
    fileList.value = []
    await load()
  } catch {
    ElMessage.error('上传失败')
  } finally {
    uploading.value = false
  }
}

async function load() {
  try {
    const res = (await listDocuments()) as unknown as { data: unknown[] }
    documents.value = res.data ?? []
  } catch {
    /* 骨架阶段忽略 */
  }
}

load()
</script>

<template>
  <div class="page">
    <el-card header="上传文档">
      <el-upload v-model:file-list="fileList" :auto-upload="false" multiple>
        <el-button>选择文件</el-button>
      </el-upload>
      <el-button type="primary" :loading="uploading" @click="onUpload">
        上传并入库
      </el-button>
    </el-card>
    <el-card header="知识库文档" class="mt">
      <el-table :data="documents" empty-text="暂无文档">
        <el-table-column prop="title" label="标题" />
        <el-table-column prop="status" label="状态" />
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  padding: 16px;
}
.mt {
  margin-top: 16px;
}
</style>
