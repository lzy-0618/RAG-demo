<script setup lang="ts">
/** 合同模板库（需求⑥）：导入 .docx → 结构化识别 → 人工复核 → 启用。
 *
 * 模板必须先完成"字段确认"（复核）才会出现在「合同生成」页，
 * 避免把未确认的占位符直接暴露给填表的人。
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRawFile, UploadUserFile } from 'element-plus'
import DocxPreview from '@/components/DocxPreview.vue'
import TemplateStructureReview from '@/components/TemplateStructureReview.vue'
import { downloadAuthedFile } from '@/api/download'
import { useMediaQuery } from '@/composables/useMediaQuery'
import { formatDateTime } from '@/utils/format'
import {
  deleteTemplate,
  listTemplates,
  seedCategories,
  uploadTemplate,
} from '@/api/template'
import type { StructureStatus, TemplateOut } from '@/api/template'

// 占位符文案放在 script 里：模板中直接写 {{ ... }} 会与 Vue 插值语法冲突
const VAR_PLACEHOLDER = '{{ 变量 }}'
const VAR_PLACEHOLDER_NAMED = '{{ 变量名 }}'

const STATUS_META: Record<
  StructureStatus,
  { text: string; type: 'success' | 'warning' | 'danger' | 'info' }
> = {
  pending: { text: '待识别', type: 'info' },
  structuring: { text: '识别中', type: 'warning' },
  review: { text: '待复核', type: 'warning' },
  ready: { text: '已启用', type: 'success' },
  failed: { text: '识别失败', type: 'danger' },
}

const templates = ref<TemplateOut[]>([])
const categories = ref<string[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const activeCategory = ref<string>('')
const loading = ref(false)

// 列可见性按可用宽度分档：宁可少显示几列，也不要让右侧固定操作列压住中间的数据。
// 9 列全宽合计约 900px，容器宽度 = 视口 - 侧栏 - 页面留白 - 卡片留白。
const showExtras = useMediaQuery('(min-width: 1245px)') // 类型、字段
const showTime = useMediaQuery('(min-width: 1061px)') // 导入时间
const showVars = useMediaQuery('(min-width: 701px)') // 占位变量

const uploadVisible = ref(false)
const uploading = ref(false)
const fileList = ref<UploadUserFile[]>([])
const form = ref({ name: '', category: '', description: '' })

const previewVisible = ref(false)
const previewRow = ref<TemplateOut | null>(null)

const reviewVisible = ref(false)
const reviewId = ref<number | null>(null)

async function load() {
  loading.value = true
  try {
    const res = await listTemplates({
      category: activeCategory.value || undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    templates.value = res.data?.items ?? []
    total.value = res.data?.total ?? 0
    categories.value = res.data?.categories ?? []
  } finally {
    loading.value = false
  }
}

function onFileChange(_file: unknown, files: UploadUserFile[]) {
  fileList.value = files
  if (!form.value.name && files[0]?.name) {
    form.value.name = files[0].name.replace(/\.docx$/i, '')
  }
}

async function onUpload() {
  const file = fileList.value[0]?.raw as UploadRawFile | undefined
  if (!file) {
    ElMessage.warning('请选择 .docx 模板文件')
    return
  }
  uploading.value = true
  try {
    const res = await uploadTemplate({
      file,
      name: form.value.name || undefined,
      category: form.value.category || undefined,
      description: form.value.description || undefined,
    })
    const created = res.data
    uploadVisible.value = false
    fileList.value = []
    form.value = { name: '', category: '', description: '' }
    page.value = 1
    await load()
    ElMessage.success('导入成功，请完成字段识别与复核后启用')
    // 导入后直接进入复核流程，减少一次点击
    openReview(created)
  } finally {
    uploading.value = false
  }
}

function openReview(row: TemplateOut) {
  reviewId.value = row.id
  reviewVisible.value = true
}

async function onDelete(row: TemplateOut) {
  await ElMessageBox.confirm(
    `确定删除模板「${row.name}」？删除后不再出现在生成页，历史生成记录仍可下载。`,
    '删除确认',
    { type: 'warning' },
  )
  await deleteTemplate(row.id)
  ElMessage.success('已删除')
  await load()
}

function onPreview(row: TemplateOut) {
  previewRow.value = row
  previewVisible.value = true
}

async function onDownload(row: TemplateOut) {
  try {
    await downloadAuthedFile(`/templates/${row.id}/download`, row.file_name || `${row.name}.docx`)
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : '下载失败')
  }
}

async function onSeedCategories() {
  const res = await seedCategories()
  ElMessage.success(res.data?.created ? `已从存量模板登记 ${res.data.created} 个类型` : '类型词表已是最新')
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page reveal-group">
    <el-card>
      <!-- 页标题由外壳的文书头统一承担，这里不再重复一遍卡片标题 -->
      <div class="bar">
        <el-select v-model="activeCategory" class="select" clearable placeholder="按类型筛选" @change="load">
          <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
        </el-select>
        <el-button type="primary" @click="uploadVisible = true">导入模板</el-button>
        <el-button text @click="onSeedCategories">同步类型词表</el-button>
        <el-button text @click="load">刷新</el-button>
        <span class="meta">.docx 模板 · 完成字段复核后才可用于生成</span>
      </div>

      <el-table v-loading="loading" :data="templates" empty-text="暂无模板">
        <el-table-column prop="name" label="模板名称" min-width="150" show-overflow-tooltip />
        <el-table-column v-if="showExtras" prop="category" label="类型" width="80" />
        <el-table-column label="结构状态" width="90">
          <template #default="{ row }">
            <el-tag :type="STATUS_META[row.structure_status as StructureStatus]?.type ?? 'info'" size="small">
              {{ STATUS_META[row.structure_status as StructureStatus]?.text ?? row.structure_status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="showExtras" label="字段" width="70">
          <template #default="{ row }">
            <span v-if="row.fields.length" class="u-num">{{ row.fields.length }} 个</span>
            <span v-else class="hint">未识别</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showVars" label="占位变量" min-width="150">
          <template #default="{ row }">
            <template v-if="row.variables.length">
              <el-tag v-for="v in row.variables.slice(0, 3)" :key="v" size="small" class="var-tag">
                {{ v }}
              </el-tag>
              <span v-if="row.variables.length > 3" class="hint u-num">
                +{{ row.variables.length - 3 }}
              </span>
            </template>
            <span v-else class="hint">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showTime" label="导入时间" width="140">
          <template #default="{ row }">
            <span class="u-tnum">{{ formatDateTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openReview(row)">
              {{ row.structure_status === 'ready' ? '字段复核' : '识别复核' }}
            </el-button>
            <el-button link type="primary" size="small" @click="onPreview(row)">预览</el-button>
            <el-button link type="primary" size="small" @click="onDownload(row)">下载</el-button>
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
        @current-change="load"
      />
    </el-card>

    <el-dialog v-model="uploadVisible" title="导入合同模板" width="560px">
      <el-form label-position="top">
        <el-form-item :label="`模板文件（.docx，可用 ${VAR_PLACEHOLDER_NAMED} 或下划线标记待填内容）`">
          <el-upload
            drag
            :auto-upload="false"
            :limit="1"
            :file-list="fileList"
            :on-change="onFileChange"
            accept=".docx"
          >
            <div class="upload-tip">拖拽 .docx 到此处，或点击选择</div>
            <div class="upload-hint">
              模板为含 {{ VAR_PLACEHOLDER }} 占位符或填空痕迹的 .docx；导入后需完成字段识别与复核才可生成合同
            </div>
          </el-upload>
        </el-form-item>
        <el-form-item label="模板名称">
          <el-input v-model="form.name" placeholder="如：钢材采购合同模板" />
        </el-form-item>
        <el-form-item label="合同类型">
          <el-select
            v-model="form.category"
            class="full"
            filterable
            allow-create
            clearable
            placeholder="从词表选择，或输入新类型"
          >
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="说明（可选）">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="onUpload">导入</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="previewVisible"
      :title="`模板预览 - ${previewRow?.name ?? ''}`"
      width="60%"
      top="5vh"
      destroy-on-close
    >
      <DocxPreview
        v-if="previewRow"
        :path="`/templates/${previewRow.id}/preview`"
        min-height="60vh"
      />
    </el-dialog>

    <TemplateStructureReview v-model="reviewVisible" :template-id="reviewId" @updated="load" />
  </div>
</template>

<style scoped>
.page {
  height: 100%;
  padding: var(--space-5);
  overflow-y: auto;
}

/* 操作条：控件左聚，说明右靠 */
.bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
  margin-bottom: var(--space-4);
}

.select {
  width: 200px;
}

.full {
  width: 100%;
}

/* 变量标签单行不换行，超出由 +N 收纳，避免把行高撑成三行 */
.var-tag {
  margin: 0 var(--space-1) var(--space-1) 0;
}

.upload-tip {
  color: var(--ink-2);
}

.upload-hint {
  margin-top: var(--space-2);
  font-size: var(--fs-xs);
  color: var(--muted);
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
