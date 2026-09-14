<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile, UploadRawFile, UploadUserFile } from 'element-plus'
import {
  createTextDocument,
  deleteDocument,
  listDatasets,
  listDocuments,
  refreshDocument,
  syncDataset,
  uploadDocument,
} from '@/api/knowledge'
import type { DatasetOut, DocumentOut } from '@/api/knowledge'

const datasets = ref<DatasetOut[]>([])
const activeKey = ref('law')
const documents = ref<DocumentOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const loading = ref(false)
const uploading = ref(false)
const syncing = ref(false)
const fileList = ref<UploadUserFile[]>([])

const textDialogVisible = ref(false)
const textForm = ref({ title: '', text: '' })
const textSubmitting = ref(false)

// Dify 索引是异步的：parsing 状态的文档需要轮询刷新状态
let pollTimer: number | undefined

const STATUS_META: Record<string, { text: string; type: 'success' | 'warning' | 'danger' | 'info' }> = {
  uploaded: { text: '已上传', type: 'info' },
  parsing: { text: '解析中', type: 'warning' },
  ready: { text: '已入库', type: 'success' },
  failed: { text: '失败', type: 'danger' },
}

const activeDataset = computed(() => datasets.value.find((d) => d.key === activeKey.value))
const hasParsing = computed(() => documents.value.some((d) => d.status === 'parsing'))

async function loadDatasets() {
  const res = await listDatasets()
  datasets.value = res.data ?? []
  const firstConfigured = datasets.value.find((d) => d.configured)
  if (firstConfigured) activeKey.value = firstConfigured.key
}

async function loadDocuments() {
  loading.value = true
  try {
    const res = await listDocuments({
      dataset_key: activeKey.value,
      page: page.value,
      page_size: pageSize.value,
    })
    documents.value = res.data?.items ?? []
    total.value = res.data?.total ?? 0
  } finally {
    loading.value = false
  }
}

function onDatasetChange() {
  page.value = 1
  loadDocuments()
}

async function onUpload() {
  const files = fileList.value
    .map((f) => f.raw)
    .filter((f): f is UploadRawFile => Boolean(f))
  if (!files.length) {
    ElMessage.warning('请先选择文件')
    return
  }
  if (!activeDataset.value?.configured) {
    ElMessage.warning('当前知识库未配置 dataset_id，请检查后端 .env')
    return
  }
  uploading.value = true
  try {
    for (const file of files) {
      await uploadDocument(activeKey.value, file)
    }
    ElMessage.success('已提交入库，正在异步解析')
    fileList.value = []
    page.value = 1
    await loadDocuments()
  } finally {
    uploading.value = false
  }
}

async function onRefresh(doc?: DocumentOut) {
  if (doc) {
    await refreshDocument(doc.id)
    await loadDocuments()
    return
  }
  await loadDocuments()
}

/** 补录 Dify 中已存在但本地没有记录的文档（历史文档） */
async function onSync() {
  syncing.value = true
  try {
    const res = await syncDataset(activeKey.value)
    const created = res.data?.created ?? 0
    ElMessage.success(created ? `已同步 ${created} 篇文档` : '本地记录已是最新')
    await loadDatasets()
    await loadDocuments()
  } finally {
    syncing.value = false
  }
}

async function onDelete(doc: DocumentOut) {
  await ElMessageBox.confirm(
    `确定删除「${doc.title}」？将同时从 Dify 知识库中移除。`,
    '删除确认',
    { type: 'warning' },
  )
  await deleteDocument(doc.id)
  ElMessage.success('已删除')
  await loadDocuments()
}

async function onTextSubmit() {
  if (!textForm.value.title.trim() || !textForm.value.text.trim()) {
    ElMessage.warning('标题与内容不能为空')
    return
  }
  textSubmitting.value = true
  try {
    await createTextDocument(activeKey.value, textForm.value.title, textForm.value.text)
    ElMessage.success('文本已提交入库')
    textDialogVisible.value = false
    textForm.value = { title: '', text: '' }
    page.value = 1
    await loadDocuments()
  } finally {
    textSubmitting.value = false
  }
}

function onFileChange(_file: UploadFile, files: UploadUserFile[]) {
  fileList.value = files
}

onMounted(async () => {
  await loadDatasets()
  await loadDocuments()
  // 每 3 秒刷新一次解析中的文档状态，全部就绪后自动停止轮询
  pollTimer = window.setInterval(async () => {
    if (!hasParsing.value) return
    for (const doc of documents.value.filter((d) => d.status === 'parsing')) {
      try {
        await refreshDocument(doc.id)
      } catch {
        /* 轮询失败不打断界面 */
      }
    }
    await loadDocuments()
  }, 3000)
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<template>
  <div class="page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>知识库</span>
          <span class="hint">共 {{ datasets.length }} 个库，当前库文档 {{ activeDataset?.document_count ?? 0 }} 篇</span>
        </div>
      </template>

      <div class="toolbar">
        <el-select v-model="activeKey" class="select" @change="onDatasetChange">
          <el-option
            v-for="d in datasets"
            :key="d.key"
            :label="d.configured ? d.name : `${d.name}（未配置）`"
            :value="d.key"
            :disabled="!d.configured"
          />
        </el-select>

        <el-upload
          :auto-upload="false"
          multiple
          :file-list="fileList"
          :on-change="onFileChange"
          :show-file-list="false"
        >
          <el-button>选择文件</el-button>
        </el-upload>
        <el-button type="primary" :loading="uploading" @click="onUpload">上传并入库</el-button>
        <el-button @click="textDialogVisible = true">文本入库</el-button>
        <el-button :loading="syncing" @click="onSync">从 Dify 同步</el-button>
        <el-button text @click="onRefresh()">刷新列表</el-button>
        <span v-if="fileList.length" class="hint">已选 {{ fileList.length }} 个文件</span>
      </div>

      <el-table v-loading="loading" :data="documents" empty-text="暂无文档">
        <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
        <el-table-column label="类型" width="80">
          <template #default="{ row }">{{ row.doc_type === 'text' ? '文本' : '文件' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tooltip v-if="row.error" :content="row.error" placement="top">
              <el-tag :type="STATUS_META[row.status]?.type ?? 'info'" size="small">
                {{ STATUS_META[row.status]?.text ?? row.status }}
              </el-tag>
            </el-tooltip>
            <el-tag v-else :type="STATUS_META[row.status]?.type ?? 'info'" size="small">
              {{ STATUS_META[row.status]?.text ?? row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="uploader" label="上传人" width="110" />
        <el-table-column prop="created_at" label="上传时间" width="170" />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="onRefresh(row)">刷新状态</el-button>
            <el-button link type="danger" size="small" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        class="pagination"
        layout="total, prev, pager, next"
        :total="total"
        @current-change="loadDocuments"
      />
    </el-card>

    <el-dialog v-model="textDialogVisible" title="文本入库（审核规则 / 专家标注）" width="620px">
      <el-form label-position="top">
        <el-form-item label="标题">
          <el-input v-model="textForm.title" placeholder="如：差旅住宿费超标处理规则" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="textForm.text" type="textarea" :rows="8" placeholder="规则 / 纠错内容正文" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="textDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="textSubmitting" @click="onTextSubmit">提交入库</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  padding: 16px;
  height: 100%;
  overflow-y: auto;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.select {
  width: 220px;
}
.hint {
  color: #909399;
  font-size: 13px;
}
.pagination {
  margin-top: 14px;
  justify-content: flex-end;
}
</style>
