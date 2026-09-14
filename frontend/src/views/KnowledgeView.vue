<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile, UploadRawFile, UploadUserFile } from 'element-plus'
import {
  deleteDocument,
  listDatasets,
  listDocuments,
  refreshDocument,
  syncDataset,
  uploadDocument,
} from '@/api/knowledge'
import type { DatasetOut, DocumentOut } from '@/api/knowledge'
import { useMediaQuery } from '@/composables/useMediaQuery'
import { formatDateTime } from '@/utils/format'

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

// 六列全宽合计约 750px；窄于 1100 时收起次要列，
// 否则右侧固定操作列会压住「上传人 / 上传时间」
const showExtras = useMediaQuery('(min-width: 1100px)')

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
  <div class="page reveal-group">
    <el-card>
      <!-- 页标题由外壳的文书头统一承担，这里不再重复一遍卡片标题 -->
      <div class="bar">
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
        <el-button :loading="syncing" @click="onSync">从 Dify 同步</el-button>
        <el-button text @click="onRefresh()">刷新列表</el-button>

        <span v-if="fileList.length" class="hint">已选 {{ fileList.length }} 个文件</span>
        <span class="meta u-num">
          共 {{ datasets.length }} 个库 · 当前库 {{ activeDataset?.document_count ?? 0 }} 篇
        </span>
      </div>

      <el-table v-loading="loading" :data="documents" empty-text="暂无文档">
        <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
        <el-table-column v-if="showExtras" label="类型" width="80">
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
        <el-table-column v-if="showExtras" prop="uploader" label="上传人" width="100" />
        <el-table-column v-if="showExtras" label="上传时间" width="150">
          <template #default="{ row }">
            <span class="u-tnum">{{ formatDateTime(row.created_at) }}</span>
          </template>
        </el-table-column>
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
  </div>
</template>

<style scoped>
.page {
  height: 100%;
  padding: var(--space-5);
  overflow-y: auto;
}

/* 操作条：控件左聚，统计信息右靠并走等宽，替代原来卡片头里的两段文字 */
.bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
  margin-bottom: var(--space-4);
}

.select {
  width: 220px;
}

.hint {
  font-size: var(--fs-sm);
  color: var(--muted);
}

.meta {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.pagination {
  justify-content: flex-end;
  margin-top: var(--space-4);
}
</style>
