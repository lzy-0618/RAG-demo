<script setup lang="ts">
/** 合同生成（需求⑦）：选类型 → 选模板 → 左侧预览 / 右侧按字段 schema 填表 →
 *  docxtpl 确定性填充 → 落库并下载。**不调用大模型**，模板即权威。
 *
 * 预览三层：打开模板出原始预览 → 填字后后端按真实渲染出草稿预览（覆盖 `{% for %}` 等
 *  前端替换搞不定的情况）→ 生成后切换为终稿预览，保证"看到的 = 下载到的"。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import DocxPreview from '@/components/DocxPreview.vue'
import { downloadAuthedFile } from '@/api/download'
import {
  deleteContractRecord,
  generateContract,
  listCategories,
  listContractRecords,
  listTemplates,
  previewContractDraft,
} from '@/api/template'
import type { ContractRecord, TemplateOut } from '@/api/template'
import { formatDateTime } from '@/utils/format'

const templates = ref<TemplateOut[]>([])
const records = ref<ContractRecord[]>([])
const recordTotal = ref(0)
const categories = ref<string[]>([])
const activeCategory = ref('')
const templateId = ref<number | null>(null)
const values = ref<Record<string, string>>({})
const submitting = ref(false)

const previewMode = ref<'template' | 'draft' | 'record'>('template')
const draftId = ref('')
const recordId = ref<number | null>(null)
const draftLoading = ref(false)

const previewPath = computed(() => {
  if (previewMode.value === 'record' && recordId.value) {
    return `/generate/contract/records/${recordId.value}/preview`
  }
  if (previewMode.value === 'draft' && draftId.value) {
    return `/generate/contract/preview/${draftId.value}`
  }
  return templateId.value ? `/templates/${templateId.value}/preview` : ''
})

const readyTemplates = computed(() =>
  templates.value.filter((t) => t.structure_status === 'ready'),
)
const visibleTemplates = computed(() =>
  activeCategory.value
    ? readyTemplates.value.filter((t) => t.category === activeCategory.value)
    : readyTemplates.value,
)
const current = computed(() => templates.value.find((t) => t.id === templateId.value) ?? null)
const missingRequired = computed(() =>
  (current.value?.fields ?? [])
    .filter((field) => field.required && !(values.value[field.key] ?? '').trim())
    .map((field) => field.label),
)

let draftTimer: number | undefined

async function load() {
  const [res, cats] = await Promise.all([
    listTemplates({ page_size: 100 }),
    listCategories(),
  ])
  templates.value = res.data?.items ?? []
  categories.value = cats.data?.items ?? []
  if (!templateId.value) {
    const first = visibleTemplates.value[0]
    if (first) selectTemplate(first.id)
  }
  await loadRecords()
}

async function loadRecords() {
  const res = await listContractRecords({ page: 1, page_size: 10 })
  records.value = res.data?.items ?? []
  recordTotal.value = res.data?.total ?? 0
}

function selectTemplate(id: number) {
  templateId.value = id
  previewMode.value = 'template'
  draftId.value = ''
  recordId.value = null
  const template = templates.value.find((t) => t.id === id)
  const next: Record<string, string> = {}
  for (const field of template?.fields ?? []) {
    // 保留已填过且仍然存在的值（换模板时不清空同名项）
    next[field.key] = values.value[field.key] ?? field.default ?? ''
  }
  values.value = next
}

/** 停止输入后按真实渲染刷新草稿预览（防抖，避免每次按键都渲染文档） */
function scheduleDraftPreview() {
  if (!templateId.value) return
  window.clearTimeout(draftTimer)
  draftTimer = window.setTimeout(async () => {
    if (!templateId.value) return
    draftLoading.value = true
    try {
      const res = await previewContractDraft(templateId.value, values.value)
      draftId.value = res.data?.preview_id ?? ''
      if (draftId.value) previewMode.value = 'draft'
    } catch {
      /* 预览失败不打断填表，生成时会给出明确错误 */
    } finally {
      draftLoading.value = false
    }
  }, 700)
}

watch(values, scheduleDraftPreview, { deep: true })
watch(activeCategory, () => {
  if (current.value && activeCategory.value && current.value.category !== activeCategory.value) {
    const first = visibleTemplates.value[0]
    if (first) selectTemplate(first.id)
  }
})

async function onSubmit() {
  if (!templateId.value) {
    ElMessage.warning('请选择合同模板')
    return
  }
  if (missingRequired.value.length) {
    ElMessage.warning(`以下必填项未填写：${missingRequired.value.join('、')}`)
    return
  }
  submitting.value = true
  try {
    const res = await generateContract(templateId.value, values.value)
    recordId.value = res.data.record_id
    previewMode.value = 'record'
    if (res.data.missing_variables.length) {
      ElMessage.warning(`有 ${res.data.missing_variables.length} 个非必填项留空`)
    } else {
      ElMessage.success('合同已生成')
    }
    await loadRecords()
  } finally {
    submitting.value = false
  }
}

async function onDownload(record?: ContractRecord) {
  const target = record ?? records.value.find((item) => item.id === recordId.value)
  if (!target) return
  try {
    await downloadAuthedFile(
      `/generate/contract/records/${target.id}/download`,
      target.file_name,
    )
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : '下载失败')
  }
}

function onReuse(record: ContractRecord) {
  const template = templates.value.find((t) => t.id === record.template_id)
  if (!template) {
    ElMessage.warning('原模板已不存在，无法以此为基础重新生成')
    return
  }
  selectTemplate(template.id)
  values.value = { ...values.value, ...record.values }
  ElMessage.success('已载入该记录的取值')
}

async function onDeleteRecord(record: ContractRecord) {
  await ElMessageBox.confirm(`删除生成记录「${record.template_name}」及其产物？`, '删除确认', {
    type: 'warning',
  })
  await deleteContractRecord(record.id)
  if (recordId.value === record.id) {
    recordId.value = null
    previewMode.value = 'template'
  }
  ElMessage.success('已删除')
  await loadRecords()
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="split reveal-group">
      <el-card class="pane preview-pane">
        <template #header>
          <div class="card-header">
            <span>
              预览
              <el-tag v-if="previewMode === 'draft'" size="small" type="warning">草稿（按当前取值）</el-tag>
              <el-tag v-else-if="previewMode === 'record'" size="small" type="success">终稿</el-tag>
            </span>
            <div class="header-actions">
              <el-button
                v-if="previewMode !== 'template' && templateId"
                link
                type="primary"
                @click="previewMode = 'template'"
              >
                查看模板原文
              </el-button>
              <el-button
                v-if="recordId"
                type="primary"
                size="small"
                @click="onDownload()"
              >
                下载 Word
              </el-button>
            </div>
          </div>
        </template>
        <DocxPreview v-if="previewPath" :key="previewPath" :path="previewPath" min-height="62vh" />
        <el-empty v-else description="请先选择模板" />
      </el-card>

      <el-card class="pane form-pane">
        <template #header>
          <div class="card-header">
            <span>填写合同要素</span>
            <span v-if="draftLoading" class="hint">正在生成草稿预览…</span>
          </div>
        </template>

        <el-form label-position="top">
          <el-form-item label="合同类型">
            <el-select v-model="activeCategory" clearable placeholder="全部类型" class="full">
              <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
            </el-select>
          </el-form-item>
          <el-form-item label="合同模板">
            <el-select
              :model-value="templateId"
              class="full"
              placeholder="请选择已启用的模板"
              @change="selectTemplate"
            >
              <el-option
                v-for="t in visibleTemplates"
                :key="t.id"
                :label="`${t.name}（${t.fields.length} 个字段）`"
                :value="t.id"
              />
            </el-select>
            <span v-if="!readyTemplates.length" class="hint">
              暂无已启用的模板，请先到「合同模板库管理」完成字段识别与复核
            </span>
          </el-form-item>
        </el-form>

        <el-divider v-if="current" content-position="left">
          合同要素（{{ current.fields.length }} 项，必填 {{ missingRequired.length }} 项待填）
        </el-divider>

        <el-form v-if="current" label-position="top" class="field-form">
          <el-form-item v-for="field in current.fields" :key="field.key" :required="field.required">
            <template #label>
              <span>{{ field.label }}</span>
              <span class="key-hint">{{ field.key }}</span>
            </template>
            <el-select
              v-if="field.type === 'select'"
              v-model="values[field.key]"
              class="full"
              clearable
            >
              <el-option v-for="opt in field.options" :key="opt" :label="opt" :value="opt" />
            </el-select>
            <el-checkbox v-else-if="field.type === 'checkbox'" v-model="values[field.key]" :true-value="'是'" :false-value="'否'" />
            <el-date-picker
              v-else-if="field.type === 'date'"
              v-model="values[field.key]"
              class="full"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="选择日期"
            />
            <el-input
              v-else-if="field.type === 'number'"
              v-model="values[field.key]"
              class="full"
              type="number"
              :placeholder="`请输入${field.label}`"
            />
            <el-input
              v-else-if="field.type === 'textarea'"
              v-model="values[field.key]"
              type="textarea"
              :rows="3"
              :placeholder="`请输入${field.label}`"
            />
            <el-input v-else v-model="values[field.key]" :placeholder="`请输入${field.label}`" />
          </el-form-item>
        </el-form>

        <div class="actions">
          <el-button
            type="primary"
            :loading="submitting"
            :disabled="!templateId"
            @click="onSubmit"
          >
            生成合同初稿
          </el-button>
          <span v-if="missingRequired.length" class="hint warn">
            待填：{{ missingRequired.join('、') }}
          </span>
        </div>

        <el-divider content-position="left">生成记录</el-divider>
        <!-- 右栏内嵌表格可用宽度有限：把时间与生成人收到模板名下方成两行，
             列数就不会超出容器、被右侧固定操作列压住 -->
        <el-table :data="records" size="small" empty-text="暂无生成记录" max-height="240">
          <el-table-column label="模板 / 生成信息" min-width="200">
            <template #default="{ row }">
              <div class="rec-name">{{ row.template_name }}</div>
              <div class="rec-meta">
                <span class="u-tnum">{{ formatDateTime(row.created_at) }}</span>
                <span v-if="row.created_by"> · {{ row.created_by }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="onDownload(row)">下载</el-button>
              <el-button link type="primary" size="small" @click="onReuse(row)">复用</el-button>
              <el-button link type="danger" size="small" @click="onDeleteRecord(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="recordTotal > records.length" class="hint">
          共 {{ recordTotal }} 条，仅显示最近 {{ records.length }} 条
        </div>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.page {
  height: 100%;
  padding: var(--space-5);
  overflow-y: auto;
}

/* 左预览承载阅读、右表单承载填写，比例再往预览侧推一点 */
.split {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(360px, 1fr);
  gap: var(--space-5);
  align-items: start;
}

.pane {
  min-width: 0;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.full {
  width: 100%;
}

.field-form {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 0 var(--space-4);
}

/* 模板占位符键名：等宽小字，与中文标签区分开 */
.key-hint {
  margin-left: var(--space-2);
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  color: var(--muted);
}

/* 生成记录：主行是模板名，次行是时间与生成人 */
.rec-name {
  color: var(--ink);
}

.rec-meta {
  margin-top: 2px;
  font-size: var(--fs-2xs);
  color: var(--muted);
}

/* .hint 由 styles/patterns.css 提供，此处不再重复定义 */
.warn {
  color: var(--warn);
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
  margin-top: var(--space-1);
}
</style>
