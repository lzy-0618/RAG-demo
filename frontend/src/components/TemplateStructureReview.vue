<script setup lang="ts">
/** 模板结构化复核（P2）：左侧看模板预览，右侧校对字段清单。
 *
 * 识别结果**不直接生效**——AI 判断必然有错，而合同出错代价高，所以复核对完才能启用。
 * 复核页同时承担"字段配置"职责：改中文标签、控件类型、是否必填，也可从候选空位手动补字段。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import DocxPreview from '@/components/DocxPreview.vue'
import {
  getTemplate,
  listCategories,
  resetTemplateStructure,
  saveTemplateFields,
  structureTemplate,
} from '@/api/template'
import type { TemplateCandidate, TemplateDetail, TemplateField } from '@/api/template'

const props = defineProps<{ modelValue: boolean; templateId: number | null }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  updated: []
}>()

const FIELD_TYPES = [
  { value: 'text', label: '单行文本' },
  { value: 'textarea', label: '多行文本' },
  { value: 'date', label: '日期' },
  { value: 'number', label: '数字' },
  { value: 'select', label: '下拉选择' },
  { value: 'checkbox', label: '勾选' },
]

/** 候选类型 → 中文。给复核人看「这处空位是怎么被找到的」，比显示英文 kind 有用 */
const KIND_LABELS: Record<string, string> = {
  form_field: '表单域',
  hash: '#占位符',
  jinja: '已有占位符',
  sdt: '内容控件',
  blank: '下划线填空',
  label_empty: '空标签',
  empty_cell: '空单元格',
}

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind
}

const STATUS_META: Record<string, { text: string; type: 'success' | 'warning' | 'danger' | 'info' }> = {
  pending: { text: '待识别', type: 'info' },
  structuring: { text: '识别中', type: 'warning' },
  review: { text: '待复核', type: 'warning' },
  ready: { text: '已启用', type: 'success' },
  failed: { text: '识别失败', type: 'danger' },
}

const detail = ref<TemplateDetail | null>(null)
const fields = ref<TemplateField[]>([])
const contractType = ref('')
const categories = ref<string[]>([])
const loading = ref(false)
const structuring = ref(false)
const saving = ref(false)
const warnings = ref<string[]>([])
const addCandidateId = ref('')

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const statusMeta = computed(() => STATUS_META[detail.value?.structure_status ?? 'pending'])
// 一个字段可能有多个落点，全部算"已占用"，否则手动补字段时会重复挑到同一处
const usedCandidates = computed(
  () => new Set(fields.value.flatMap((f) => [...(f.candidate_ids ?? []), f.candidate_id]).filter(Boolean)),
)
const unusedCandidates = computed<TemplateCandidate[]>(
  () => (detail.value?.candidates ?? []).filter((c) => !usedCandidates.value.has(c.id)),
)
const missingKeys = computed(() => fields.value.some((f) => !f.key.trim() || !f.label.trim()))

async function load() {
  if (!props.templateId) return
  loading.value = true
  warnings.value = []
  try {
    const [res, cats] = await Promise.all([getTemplate(props.templateId), listCategories()])
    detail.value = res.data
    categories.value = cats.data?.items ?? []
    // 深拷贝：编辑不应污染详情缓存，取消时能还原
    fields.value = (res.data.fields ?? []).map((field) => ({ ...field }))
    contractType.value = res.data.category ?? ''
  } finally {
    loading.value = false
  }
}

async function runStructure() {
  if (!props.templateId) return
  if (detail.value?.fields?.length) {
    await ElMessageBox.confirm(
      '重新识别会覆盖当前字段定义，确定继续？',
      '重新识别',
      { type: 'warning' },
    )
  }
  structuring.value = true
  try {
    const res = await structureTemplate(props.templateId)
    warnings.value = ((res.data as { warnings?: string[] }).warnings ?? []).slice(0, 5)
    ElMessage.success('识别完成，请复核字段后启用')
    await load()
    emit('updated')
  } finally {
    structuring.value = false
  }
}

async function onSave(enable: boolean) {
  if (!props.templateId) return
  if (!fields.value.length) {
    ElMessage.warning('至少需要一个字段')
    return
  }
  if (missingKeys.value) {
    ElMessage.warning('字段键与中文标签都不能为空')
    return
  }
  saving.value = true
  try {
    await saveTemplateFields(props.templateId, {
      fields: fields.value,
      contract_type: contractType.value || undefined,
      enable,
    })
    ElMessage.success(enable ? '已保存并启用' : '已保存（未启用）')
    await load()
    emit('updated')
    if (enable) visible.value = false
  } finally {
    saving.value = false
  }
}

async function onReset() {
  if (!props.templateId) return
  await resetTemplateStructure(props.templateId)
  ElMessage.success('已重置为待识别')
  await load()
  emit('updated')
}

function addField() {
  const candidate = unusedCandidates.value.find((c) => c.id === addCandidateId.value)
  const index = fields.value.length + 1
  fields.value.push({
    // 具名候选（表单域 / #占位符）沿用模板原名做 key，与 AI 识别路径保持一致
    key: candidate?.name || `field_${index}`,
    label: candidate ? fieldLabelFromCandidate(candidate) : '',
    type: 'text',
    required: false,
    default: '',
    options: [],
    anchor: candidate?.anchor ?? '',
    anchors: candidate ? [candidate.anchor] : [],
    candidate_id: candidate?.id ?? '',
    candidate_ids: candidate ? [candidate.id] : [],
    slot_id: '',
    source_name: candidate?.name ?? '',
    owner: '',
    paragraph_text: candidate?.context ?? '',
    confidence: 0,
    reason: '',
  })
  addCandidateId.value = ''
}

function fieldLabelFromCandidate(candidate: TemplateCandidate): string {
  if (candidate.header) return candidate.header
  // 有原名时用它更直白（#供应商名称# → 供应商名称）
  if (candidate.name) return candidate.name
  const text = candidate.context || candidate.text
  const match = text.match(/^(.{1,20}?)[：:]/)
  return match ? match[1] : text.slice(0, 12)
}

/** 字段落点数量：大于 1 表示同一个变量在文档里出现多处，填一次多处生效 */
function occurrenceCount(field: TemplateField): number {
  return (field.candidate_ids ?? []).length || (field.candidate_id ? 1 : 0)
}

function removeField(index: number) {
  fields.value.splice(index, 1)
}

function optionsText(field: TemplateField): string {
  return (field.options ?? []).join(',')
}

function onOptionsInput(field: TemplateField, value: string) {
  field.options = value
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function move(index: number, delta: number) {
  const target = index + delta
  if (target < 0 || target >= fields.value.length) return
  const [item] = fields.value.splice(index, 1)
  fields.value.splice(target, 0, item)
}

watch(
  () => [props.modelValue, props.templateId],
  ([open]) => {
    if (open) load()
  },
  { immediate: true },
)
</script>

<template>
  <el-dialog
    v-model="visible"
    title="模板结构化复核"
    width="96%"
    top="3vh"
    class="structure-dialog"
    destroy-on-close
  >
    <div v-loading="loading" class="body">
      <div class="left">
        <div class="pane-title">模板预览</div>
        <DocxPreview
          v-if="templateId"
          :path="`/templates/${templateId}/preview`"
          min-height="52vh"
        />
      </div>

      <div class="right">
        <div class="head">
          <span class="name">{{ detail?.name }}</span>
          <el-tag :type="statusMeta.type" size="small">{{ statusMeta.text }}</el-tag>
          <span class="hint">v{{ detail?.version }}</span>
          <span class="hint">{{ detail?.candidates?.length ?? 0 }} 个候选空位</span>
        </div>

        <el-alert
          v-if="detail?.error"
          class="tip"
          type="error"
          :closable="false"
          title="上次识别失败"
          :description="detail.error"
          show-icon
        />
        <el-alert
          v-for="(warning, index) in warnings"
          :key="index"
          class="tip"
          type="warning"
          :closable="false"
          :title="warning"
        />

        <div class="toolbar">
          <el-button type="primary" :loading="structuring" @click="runStructure">
            {{ detail?.fields?.length ? '重新识别' : '开始识别' }}
          </el-button>
          <el-button :disabled="structuring" @click="onReset">重置</el-button>
          <span class="hint">
            识别会调用 Dify 应用六；也可以直接从候选空位手动补字段
          </span>
        </div>

        <div class="toolbar">
          <el-select
            v-model="contractType"
            class="type-select"
            filterable
            allow-create
            clearable
            placeholder="合同类型（可选可新建）"
          >
            <el-option v-for="name in categories" :key="name" :label="name" :value="name" />
          </el-select>
          <el-select v-model="addCandidateId" class="candidate-select" clearable placeholder="从候选空位补充字段">
            <el-option
              v-for="candidate in unusedCandidates"
              :key="candidate.id"
              :label="`${kindLabel(candidate.kind)} · ${(candidate.name || candidate.context || candidate.text || '空单元格').slice(0, 28)}`"
              :value="candidate.id"
            />
          </el-select>
          <el-button :disabled="!addCandidateId" @click="addField">添加字段</el-button>
          <span class="hint">共 {{ unusedCandidates.length }} 个候选未采用</span>
        </div>

        <el-table :data="fields" size="small" height="42vh" empty-text="暂无字段，请先识别或手动添加">
          <el-table-column label="变量名" width="180">
            <template #default="{ row }">
              <!-- 模板原名就是占位符名（表单域 / #占位符 沿用甲方既有字段码），只读展示 -->
              <span class="var-name">{{ row.key }}</span>
              <el-tag v-if="row.owner" size="small" class="owner-tag" type="info">{{ row.owner }}</el-tag>
              <span v-if="occurrenceCount(row) > 1" class="occurrence" :title="`文档中出现 ${occurrenceCount(row)} 处，填一次多处生效`">
                ×{{ occurrenceCount(row) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="中文标签" width="140">
            <template #default="{ row }">
              <el-input v-model="row.label" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="类型" width="140">
            <template #default="{ row }">
              <el-select v-model="row.type" size="small" class="full">
                <el-option
                  v-for="item in FIELD_TYPES"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </el-select>
              <!-- 选项只对下拉类型有意义，收在同一个格子里，不单独占一列 -->
              <el-input
                v-if="row.type === 'select'"
                :model-value="optionsText(row)"
                size="small"
                class="full options-input"
                placeholder="选项，逗号分隔"
                @update:model-value="onOptionsInput(row, $event)"
              />
            </template>
          </el-table-column>
          <el-table-column label="必填" width="56" align="center">
            <template #default="{ row }">
              <el-checkbox v-model="row.required" />
            </template>
          </el-table-column>
          <el-table-column label="默认值" width="90">
            <template #default="{ row }">
              <el-input v-model="row.default" size="small" />
            </template>
          </el-table-column>
          <!-- 不加 fixed：对话框内宽度有限，溢出时整体横向滚动，好过固定列盖住数据 -->
          <el-table-column label="操作" width="100">
            <template #default="{ $index }">
              <el-button link size="small" @click="move($index, -1)">↑</el-button>
              <el-button link size="small" @click="move($index, 1)">↓</el-button>
              <el-button link type="danger" size="small" @click="removeField($index)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <template #footer>
      <span class="footer-hint">
        共 {{ fields.length }} 个字段；启用后模板才会出现在「合同生成」页
      </span>
      <el-button @click="visible = false">取消</el-button>
      <el-button :loading="saving" @click="onSave(false)">仅保存</el-button>
      <el-button type="primary" :loading="saving" @click="onSave(true)">保存并启用</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.body {
  display: grid;
  /* 预览是参照物、字段表是要动的地方，把宽度让给后者 */
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.55fr);
  gap: var(--space-4);
  min-height: 60vh;
}

.left,
.right {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.pane-title {
  margin: 0 0 var(--space-2);
  font-family: var(--font-serif);
  font-size: var(--fs-md);
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--ink);
}

.head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.head .name {
  font-family: var(--font-serif);
  font-size: var(--fs-lg);
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--ink);
}

.toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  margin-bottom: var(--space-3);
}

/* .hint 由 styles/patterns.css 提供，此处不再重复定义 */
.tip {
  margin-bottom: var(--space-2);
}

.type-select {
  width: 140px;
}

.candidate-select {
  width: 260px;
}

.full {
  width: 100%;
}

.var-name {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: var(--fs-xs);
  word-break: break-all;
}

.owner-tag {
  margin-left: var(--space-1);
}

/* 同一个变量在文档里出现多处时提示"填一次多处生效" */
.occurrence {
  margin-left: var(--space-1);
  font-size: var(--fs-xs);
  color: var(--muted);
}

.options-input {
  margin-top: var(--space-1);
}

.footer-hint {
  float: left;
  font-size: var(--fs-xs);
  line-height: 32px;
  color: var(--muted);
}
</style>
