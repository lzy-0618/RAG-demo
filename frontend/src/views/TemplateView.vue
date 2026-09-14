<script setup lang="ts">
/** 合同模板库（需求⑥）：导入含 {{ 变量 }} 占位符的 .docx 模板、分类管理、下载与删除。 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRawFile, UploadUserFile } from 'element-plus'
import { deleteTemplate, listTemplates, uploadTemplate } from '@/api/template'
import type { TemplateOut } from '@/api/template'

// 占位符文案放在 script 里：模板中直接写 {{ ... }} 会与 Vue 插值语法冲突
const VAR_PLACEHOLDER = '{{ 变量 }}'
const VAR_PLACEHOLDER_NAMED = '{{ 变量名 }}'

const templates = ref<TemplateOut[]>([])
const categories = ref<string[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const activeCategory = ref<string>('')
const loading = ref(false)

const uploadVisible = ref(false)
const uploading = ref(false)
const fileList = ref<UploadUserFile[]>([])
const form = ref({ name: '', category: '', description: '' })

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
  // 未填名称时默认取文件名（去掉扩展名）
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
    const vars = res.data.variables ?? []
    ElMessage.success(
      vars.length
        ? `导入成功，识别到 ${vars.length} 个占位变量`
        : '导入成功（未识别到 {{ 变量 }} 占位符，请检查模板）',
    )
    uploadVisible.value = false
    fileList.value = []
    form.value = { name: '', category: '', description: '' }
    page.value = 1
    await load()
  } finally {
    uploading.value = false
  }
}

async function onDelete(row: TemplateOut) {
  await ElMessageBox.confirm(`确定删除模板「${row.name}」？`, '删除确认', { type: 'warning' })
  await deleteTemplate(row.id)
  ElMessage.success('已删除')
  await load()
}

function onDownload(row: TemplateOut) {
  const base = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const token = localStorage.getItem('token') || ''
  // 模板下载用一次性 token 查询参数不可行，改为 fetch + blob
  fetch(`${base}/templates/${row.id}/download`, { headers: { Authorization: `Bearer ${token}` } })
    .then((resp) => {
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      return resp.blob()
    })
    .then((blob) => {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = row.file_name || `${row.name}.docx`
      a.click()
      URL.revokeObjectURL(url)
    })
    .catch(() => ElMessage.error('下载失败'))
}

function formatSize(size: number) {
  return size > 1024 * 1024 ? `${(size / 1024 / 1024).toFixed(1)} MB` : `${Math.round(size / 1024)} KB`
}

onMounted(load)
</script>

<template>
  <div class="page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>合同模板库</span>
          <span class="hint">模板为含 {{ VAR_PLACEHOLDER }} 占位符的 .docx，供「合同生成」填充</span>
        </div>
      </template>

      <div class="toolbar">
        <el-select v-model="activeCategory" class="select" clearable placeholder="按分类筛选" @change="load">
          <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
        </el-select>
        <el-button type="primary" @click="uploadVisible = true">导入模板</el-button>
        <el-button text @click="load">刷新</el-button>
      </div>

      <el-table v-loading="loading" :data="templates" empty-text="暂无模板">
        <el-table-column prop="name" label="模板名称" min-width="200" show-overflow-tooltip />
        <el-table-column prop="category" label="分类" width="110" />
        <el-table-column label="占位变量" min-width="220">
          <template #default="{ row }">
            <template v-if="row.variables.length">
              <el-tag v-for="v in row.variables.slice(0, 6)" :key="v" size="small" class="var-tag">
                {{ v }}
              </el-tag>
              <span v-if="row.variables.length > 6" class="hint">
                +{{ row.variables.length - 6 }}
              </span>
            </template>
            <span v-else class="hint">未识别到占位符</span>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="90">
          <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column prop="uploader" label="导入人" width="100" />
        <el-table-column prop="created_at" label="导入时间" width="170" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
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
        <el-form-item :label="`模板文件（.docx，正文中用 ${VAR_PLACEHOLDER_NAMED} 标记待填内容）`">
          <el-upload
            drag
            :auto-upload="false"
            :limit="1"
            :file-list="fileList"
            :on-change="onFileChange"
            accept=".docx"
          >
            <div class="upload-tip">拖拽 .docx 到此处，或点击选择</div>
          </el-upload>
        </el-form-item>
        <el-form-item label="模板名称">
          <el-input v-model="form.name" placeholder="如：钢材采购合同模板" />
        </el-form-item>
        <el-form-item label="合同类型">
          <el-input v-model="form.category" placeholder="如：采购 / 销售 / 服务" />
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
  gap: 10px;
  margin-bottom: 14px;
  align-items: center;
}
.select {
  width: 200px;
}
.hint {
  color: #909399;
  font-size: 13px;
}
.var-tag {
  margin: 2px 6px 2px 0;
}
.upload-tip {
  color: #606266;
}
.pagination {
  margin-top: 14px;
  justify-content: flex-end;
}
</style>
