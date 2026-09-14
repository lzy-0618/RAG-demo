<script setup lang="ts">
/** 合同生成（需求⑦）：选模板 → 按占位变量填表 → docxtpl 确定性填充 → 下载 Word 初稿。 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { downloadGeneratedFile, generateContract, listTemplates } from '@/api/template'
import type { TemplateOut } from '@/api/template'

const templates = ref<TemplateOut[]>([])
const templateId = ref<number | null>(null)
const values = ref<Record<string, string>>({})
const submitting = ref(false)
const result = ref<{ file_name: string; template_name: string; missing_variables: string[] } | null>(null)

const current = computed(() => templates.value.find((t) => t.id === templateId.value) ?? null)
const missing = computed(() => current.value?.variables.filter((k) => !values.value[k]?.trim()) ?? [])

async function load() {
  const res = await listTemplates({ page_size: 100 })
  templates.value = res.data?.items ?? []
  if (templates.value.length && templateId.value === null) {
    onTemplateChange(templates.value[0].id)
  }
}

function onTemplateChange(id: number) {
  templateId.value = id
  result.value = null
  const tpl = templates.value.find((t) => t.id === id)
  const next: Record<string, string> = {}
  // 保留已填过且仍然存在的变量值
  for (const key of tpl?.variables ?? []) next[key] = values.value[key] ?? ''
  values.value = next
}

async function onSubmit() {
  if (!templateId.value) {
    ElMessage.warning('请选择合同模板')
    return
  }
  submitting.value = true
  try {
    const res = await generateContract(templateId.value, values.value)
    result.value = res.data
    if (res.data.missing_variables.length) {
      ElMessage.warning(`有 ${res.data.missing_variables.length} 个变量未填写，已按空值生成`)
    } else {
      ElMessage.success('合同初稿已生成')
    }
  } finally {
    submitting.value = false
  }
}

async function onDownload() {
  if (!result.value) return
  try {
    await downloadGeneratedFile(result.value.file_name)
  } catch {
    ElMessage.error('下载失败')
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>合同生成</span>
          <span class="hint">基于「合同模板库」的模板填充，确定性命中占位变量，不调用大模型</span>
        </div>
      </template>

      <el-form label-position="top">
        <el-form-item label="选择合同模板">
          <el-select v-model="templateId" class="select" placeholder="请选择模板" @change="onTemplateChange">
            <el-option
              v-for="t in templates"
              :key="t.id"
              :label="t.category ? `${t.name}（${t.category}）` : t.name"
              :value="t.id"
            />
          </el-select>
          <span v-if="!templates.length" class="hint">
            暂无模板，请先到「合同模板库」导入 .docx 模板
          </span>
        </el-form-item>
      </el-form>

      <el-divider v-if="current" content-position="left">
        填写模板变量（{{ current.variables.length }} 个）
      </el-divider>

      <el-form v-if="current" label-position="top" class="var-form">
        <el-form-item v-for="key in current.variables" :key="key" :label="key">
          <el-input v-model="values[key]" :placeholder="`请输入 ${key}`" />
        </el-form-item>
      </el-form>

      <div class="actions">
        <el-button type="primary" :loading="submitting" :disabled="!templateId" @click="onSubmit">
          生成合同初稿
        </el-button>
        <el-button v-if="result" @click="onDownload">下载 Word</el-button>
        <span v-if="missing.length" class="hint">待填：{{ missing.join('、') }}</span>
      </div>

      <el-alert
        v-if="result"
        class="result"
        type="success"
        :closable="false"
        :title="`已生成：${result.file_name}`"
        :description="result.missing_variables.length ? `以下变量未填写，已按空值生成：${result.missing_variables.join('、')}` : '所有占位变量均已填充'"
      />
    </el-card>
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
.hint {
  color: #909399;
  font-size: 13px;
  margin-left: 8px;
}
.select {
  width: 320px;
}
.var-form {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 0 16px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
}
.result {
  margin-top: 14px;
}
</style>
