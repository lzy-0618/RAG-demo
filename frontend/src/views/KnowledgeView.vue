<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile, UploadRawFile, UploadUserFile } from 'element-plus'
import {
  deleteDocument,
  listDatasets,
  listDocuments,
  listSegments,
  listChildChunks,
  refreshDocument,
  syncDataset,
  updateSegment,
  updateChildChunk,
  uploadDocument,
} from '@/api/knowledge'
import type { ChildChunkOut, DatasetOut, DocumentOut, SegmentOut } from '@/api/knowledge'
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
const detailVisible = ref(false)
const detailDoc = ref<DocumentOut | null>(null)
const segments = ref<SegmentOut[]>([])
const segmentTotal = ref(0)
const segmentPage = ref(1)
const segmentLoading = ref(false)
const docForm = ref('')
type ChildrenState = { expanded: boolean; loading: boolean; items: ChildChunkOut[]; total: number; page: number }
const children = ref<Record<string, ChildrenState>>({})
const editorVisible = ref(false)
const editing = ref<{ segmentId: string; childId?: string; content: string } | null>(null)
const saving = ref(false)

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

async function openDocument(doc: DocumentOut) {
  detailDoc.value = doc
  detailVisible.value = true
  segmentPage.value = 1
  segmentTotal.value = 0
  docForm.value = ''
  segments.value = []
  children.value = {}
  editorVisible.value = false
  await loadSegments()
}

async function loadSegments() {
  const doc = detailDoc.value
  if (!doc) return
  segmentLoading.value = true
  try {
    const res = await listSegments(doc.id, segmentPage.value)
    if (detailDoc.value?.id !== doc.id) return
    segments.value = res.data?.data ?? []
    segmentTotal.value = res.data?.total ?? 0
    docForm.value = res.data?.doc_form ?? ''
    children.value = {}
  } finally {
    segmentLoading.value = false
  }
}

async function loadChildren(segmentId: string) {
  const doc = detailDoc.value
  const state = children.value[segmentId]
  if (!doc || !state) return
  state.loading = true
  try {
    const res = await listChildChunks(doc.id, segmentId, state.page)
    if (detailDoc.value?.id !== doc.id || !children.value[segmentId]) return
    state.items = res.data?.data ?? []
    state.total = res.data?.total ?? 0
  } finally {
    state.loading = false
  }
}

async function toggleChildren(segmentId: string) {
  const state = children.value[segmentId] ?? {
    expanded: false, loading: false, items: [], total: 0, page: 1,
  }
  children.value[segmentId] = state
  state.expanded = !state.expanded
  if (state.expanded && !state.items.length) await loadChildren(segmentId)
}

function startEdit(segmentId: string, content: string, childId?: string) {
  editing.value = { segmentId, childId, content }
  editorVisible.value = true
}

async function saveEdit() {
  const doc = detailDoc.value
  const item = editing.value
  if (!doc || !item) return
  if (!item.content.trim()) {
    ElMessage.warning('分块内容不能为空')
    return
  }
  saving.value = true
  try {
    if (item.childId) {
      await updateChildChunk(doc.id, item.segmentId, item.childId, item.content)
      await loadChildren(item.segmentId)
    } else {
      await updateSegment(doc.id, item.segmentId, item.content)
      const res = await listSegments(doc.id, segmentPage.value)
      if (detailDoc.value?.id === doc.id) {
        segments.value = res.data?.data ?? []
        segmentTotal.value = res.data?.total ?? 0
      }
    }
    editorVisible.value = false
    ElMessage.success('分块已保存，Dify 正在更新索引')
  } finally {
    saving.value = false
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
        <el-table-column label="标题" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <el-button link type="primary" class="title-link" @click="openDocument(row)">{{ row.title }}</el-button>
          </template>
        </el-table-column>
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

    <el-drawer v-model="detailVisible" :title="detailDoc?.title ?? '文档分块'" size="min(760px, 95vw)" @closed="detailDoc = null">
      <div v-loading="segmentLoading" class="detail-body">
        <p class="chunk-summary">
          分块方式：{{ docForm === 'hierarchical_model' ? '父子分块' : docForm === 'qa_model' ? '问答分块' : docForm === 'text_model' ? '普通分块' : docForm || '读取中' }}
          · 共 {{ segmentTotal }} 块
          <el-button link type="primary" @click="loadSegments">刷新分块</el-button>
        </p>
        <el-empty v-if="!segmentLoading && !segments.length" description="暂无分块；若文档仍在解析，请稍后刷新" />
        <article v-for="(segment, index) in segments" :key="segment.id" class="chunk-card">
          <div class="chunk-heading">
            <strong>第 {{ segment.position ?? (segmentPage - 1) * 20 + index + 1 }} 块</strong>
            <span class="chunk-meta">{{ segment.tokens ?? segment.word_count ?? '—' }} {{ segment.tokens != null ? 'tokens' : '字' }} · {{ segment.status ?? '状态未知' }}</span>
            <el-button link type="primary" @click="startEdit(segment.id, segment.content)">修改</el-button>
          </div>
          <pre class="chunk-content">{{ segment.content }}</pre>
          <p v-if="segment.answer" class="chunk-answer">答案：{{ segment.answer }}</p>
          <template v-if="docForm === 'hierarchical_model'">
            <el-button link type="primary" @click="toggleChildren(segment.id)">
              {{ children[segment.id]?.expanded ? '收起子块' : '查看子块' }}
            </el-button>
            <div v-if="children[segment.id]?.expanded" v-loading="children[segment.id]?.loading" class="child-list">
              <p class="chunk-meta">共 {{ children[segment.id]?.total ?? 0 }} 个子块</p>
              <article v-for="(child, childIndex) in children[segment.id]?.items ?? []" :key="child.id" class="child-card">
                <div class="chunk-heading">
                  <strong>子块 {{ ((children[segment.id]?.page ?? 1) - 1) * 20 + childIndex + 1 }}</strong>
                  <span class="chunk-meta">{{ child.tokens ?? child.word_count ?? '—' }} {{ child.tokens != null ? 'tokens' : '字' }} · {{ child.status ?? '状态未知' }}</span>
                  <el-button link type="primary" @click="startEdit(segment.id, child.content, child.id)">修改</el-button>
                </div>
                <pre class="chunk-content">{{ child.content }}</pre>
              </article>
              <el-pagination
                v-if="(children[segment.id]?.total ?? 0) > 20"
                v-model:current-page="children[segment.id].page"
                layout="total, prev, pager, next"
                :page-size="20"
                :total="children[segment.id].total"
                @current-change="loadChildren(segment.id)"
              />
            </div>
          </template>
        </article>
        <el-pagination
          v-if="segmentTotal > 20"
          v-model:current-page="segmentPage"
          layout="total, prev, pager, next"
          :page-size="20"
          :total="segmentTotal"
          @current-change="loadSegments"
        />
      </div>
    </el-drawer>

    <el-dialog v-model="editorVisible" title="修改分块内容" width="min(680px, 92vw)" append-to-body>
      <el-input v-if="editing" v-model="editing.content" type="textarea" :rows="12" maxlength="20000" show-word-limit />
      <p class="chunk-meta">保存后会更新 Dify 中的分块及索引，原始上传文件不会改变。</p>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
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

.title-link { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.detail-body { min-height: 160px; }
.chunk-summary { margin: 0 0 var(--space-4); color: var(--muted); }
.chunk-card, .child-card { border: 1px solid var(--el-border-color); border-radius: 8px; padding: var(--space-4); margin-bottom: var(--space-3); }
.child-list { margin: var(--space-2) 0 0 var(--space-4); }
.child-card { background: var(--el-fill-color-lighter); }
.chunk-heading { display: flex; align-items: center; gap: var(--space-3); }
.chunk-heading .el-button { margin-left: auto; }
.chunk-meta { color: var(--muted); font-size: var(--fs-xs); }
.chunk-content { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.6; margin: var(--space-3) 0 0; }
.chunk-answer { white-space: pre-wrap; overflow-wrap: anywhere; margin-bottom: 0; }
</style>
