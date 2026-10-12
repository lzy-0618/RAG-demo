<script setup lang="ts">
/** 审查面板：合同审查与规章制度审查共用（页面不同、审查类型不同）。 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getReviewTask, submitReview } from '@/api/review'
import type { ReviewTaskOut } from '@/api/review'
import FileDropzone from '@/components/FileDropzone.vue'
import RiskNote from '@/components/RiskNote.vue'

const props = defineProps<{
  reviewType: 'contract' | 'regulation'
}>()

const inputMode = ref<'text' | 'file'>(props.reviewType === 'contract' ? 'file' : 'text')
const content = ref('')
const reviewFile = ref<File | null>(null)
const submitting = ref(false)
const task = ref<ReviewTaskOut | null>(null)

let pollTimer: number | undefined

const isRunning = computed(
  () => task.value?.status === 'pending' || task.value?.status === 'running',
)
const contractStage = computed(() =>
  task.value?.progress?.stage ?? (task.value?.status === 'completed' ? 'done' : 'upload'),
)
const processSteps = [
  { key: 'upload', label: '文档上传' },
  { key: 'parse', label: '文档解析' },
  { key: 'review', label: '条款审核' },
] as const
function stepState(index: number) {
  const current = ['upload', 'parse', 'review', 'done'].indexOf(contractStage.value)
  if (index < current) return 'done'
  if (index > current) return 'waiting'
  return task.value?.status === 'failed' ? 'failed' : 'current'
}
const progress = computed(() => {
  const t = task.value
  if (!t?.total_chunks) return 0
  const processed = t.review_type === 'contract' && t.progress
    ? t.progress.processed_chunks
    : t.completed_chunks + t.failed_chunks
  return Math.min(100, Math.round((processed / t.total_chunks) * 100))
})
const canSubmit = computed(() =>
  props.reviewType === 'contract' || inputMode.value === 'file'
    ? !!reviewFile.value
    : content.value.trim().length > 0,
)

async function onSubmit() {
  if (!canSubmit.value || submitting.value) {
    ElMessage.warning(props.reviewType === 'contract' || inputMode.value === 'file' ? '请选择待审查文件' : '请输入待审查文本')
    return
  }
  submitting.value = true
  try {
    const res = await submitReview({
      reviewType: props.reviewType,
      content: props.reviewType === 'regulation' && inputMode.value === 'text' ? content.value : undefined,
      file: props.reviewType === 'contract' || inputMode.value === 'file' ? (reviewFile.value ?? undefined) : undefined,
    })
    ElMessage.success('已提交审查，正在处理')
    task.value = null
    startPolling(res.data.task_id)
  } finally {
    submitting.value = false
  }
}

async function poll(taskId: number) {
  const res = await getReviewTask(taskId)
  task.value = res.data
  if (res.data.status === 'completed' || res.data.status === 'failed') {
    stopPolling()
    if (res.data.status === 'failed') {
      ElMessage.error(res.data.error || '审查失败')
    } else {
      ElMessage.success(res.data.result?.is_compliant ? '审查完成：未发现风险' : '审查完成：发现风险条款')
    }
  }
}

function startPolling(taskId: number) {
  stopPolling()
  poll(taskId)
  // 后端逐块审查，进度以 1.5s 轮询刷新
  pollTimer = window.setInterval(() => poll(taskId), 1500)
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

function reset() {
  stopPolling()
  task.value = null
  content.value = ''
  reviewFile.value = null
}

onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="review-panel reveal-group">
    <el-card>
      <h2 class="sec-head">提交待审查内容</h2>

      <FileDropzone
        v-if="reviewType === 'contract'"
        v-model="reviewFile"
        accept=".pdf,.doc,.docx,.md,.txt"
        hint="长文档会自动分块逐块审查；.doc 上传后自动转换为 .docx"
      />
      <el-tabs v-else v-model="inputMode">
        <el-tab-pane label="文本输入" name="text">
          <el-input
            v-model="content"
            type="textarea"
            :rows="8"
            placeholder="粘贴待审查的合同/制度文本"
          />
        </el-tab-pane>
        <el-tab-pane label="文件上传" name="file">
          <FileDropzone
            v-model="reviewFile"
            accept=".pdf,.doc,.docx,.md,.txt"
            :hint="`长文档会自动分块逐块审查；.doc 上传后自动转换为 .docx`"
          />
        </el-tab-pane>
      </el-tabs>

      <div class="actions">
        <el-button
          type="primary"
          :loading="submitting || isRunning"
          :disabled="!canSubmit || isRunning"
          @click="onSubmit"
        >
          {{ isRunning ? '审查中…' : '开始审查' }}
        </el-button>
        <el-button v-if="task" text @click="reset">清空结果</el-button>
      </div>
    </el-card>

    <el-card v-if="task" class="mt">
      <div class="sec-bar">
        <h2 class="sec-head flush">审查进度</h2>
        <span class="hint u-num">
          {{ task.status === 'completed' ? '已完成' : task.status === 'failed' ? '失败' : '进行中' }}
          <template v-if="task.review_type !== 'contract' || task.total_chunks || contractStage === 'review'">
            · 已处理 {{ task.review_type === 'contract' && task.progress ? task.progress.processed_chunks : task.completed_chunks + task.failed_chunks }}/{{ task.total_chunks || '—' }} 块
          </template>
          <template v-if="task.failed_chunks">（失败 {{ task.failed_chunks }} 块）</template>
        </span>
      </div>
      <ol v-if="task.review_type === 'contract' && task.progress" class="process-steps">
        <li
          v-for="(step, index) in processSteps"
          :key="step.key"
          class="process-step"
          :data-state="stepState(index)"
        >
          <span class="step-marker u-num">{{ String(index + 1).padStart(2, '0') }}</span>
          <div class="step-body">
            <div class="step-heading">
              <span>{{ step.label }}</span>
              <span class="step-state">{{ stepState(index) === 'done' ? '已完成' : stepState(index) === 'failed' ? '失败' : stepState(index) === 'current' ? '进行中' : '待开始' }}</span>
            </div>
            <template v-if="step.key === 'review' && stepState(index) === 'current'">
              <ul v-if="task.progress.active_chunks.length" class="chunk-list">
                <li v-for="chunk in task.progress.active_chunks" :key="chunk.index">
                  <span class="u-num">第 {{ chunk.index }} 块</span>
                  <span class="chunk-phase">{{ chunk.phase === 'retrieval' ? '数据库检索' : '大模型生成' }}</span>
                </li>
              </ul>
              <p v-else class="hint step-hint">
                {{ task.progress.processed_chunks && task.progress.processed_chunks === task.total_chunks ? '正在汇总审核结果' : '正在准备条款审核' }}
              </p>
            </template>
          </div>
        </li>
      </ol>
      <el-progress
        :percentage="progress"
        :status="task.status === 'failed' ? 'exception' : undefined"
      />
      <p v-if="task.source_name" class="hint file-name">文件：{{ task.source_name }}</p>
      <el-alert v-if="task.status === 'failed' && task.error" class="mt" :title="task.error" type="error" :closable="false" />
    </el-card>

    <el-card v-if="task?.status === 'completed' && task.result" class="mt">
      <div class="sec-bar">
        <h2 class="sec-head flush">审查结论</h2>
        <span class="verdict" :class="task.result.is_compliant ? 'is-clear' : 'is-risk'">
          <span class="verdict-dot" aria-hidden="true" />
          {{ task.result.is_compliant ? '未发现风险' : task.result.risks.length ? `发现 ${task.result.risks.length} 处风险` : '审查未完成' }}
        </span>
      </div>

      <el-alert
        :title="task.result.summary"
        :type="task.result.is_compliant ? 'success' : 'warning'"
        :closable="false"
      />

      <ul v-if="task.result.failed_details?.length" class="note-list">
        <li v-for="detail in task.result.failed_details" :key="detail.chunk_index" class="note-item">
          第 {{ detail.chunk_index }} 块<template v-if="detail.location">（{{ detail.location }}）</template>：{{ detail.error }}
        </li>
      </ul>

      <!-- 风险条目按「批注卡」呈现，呈现细节见 RiskNote 组件 -->
      <RiskNote
        v-for="(risk, i) in task.result.risks"
        :key="i"
        :index="i"
        :level="risk.risk_level"
        :location="risk.location"
        :clause="risk.clause"
        :violations="risk.violations"
        :analysis="risk.analysis"
        :citations="risk.citations"
        :case-analysis="risk.case_analysis"
        :needs-review="risk.needs_review"
        :validation-notes="risk.validation_notes"
        :reference-case="risk.reference_case"
        :suggestion="risk.suggestion"
      />
    </el-card>
  </div>
</template>

<style scoped>
.review-panel {
  height: 100%;
  padding: var(--space-5);
  overflow-y: auto;
}

.mt {
  margin-top: var(--space-5);
}

/* 区段头、状态标记、批注卡是跨页面复用版式，统一定义在 styles/patterns.css */
.actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-4);
}

.file-name {
  margin: var(--space-3) 0 0;
}

.process-steps {
  display: grid;
  gap: 0;
  margin: 0 0 var(--space-5);
  padding: 0;
  list-style: none;
}

.process-step {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: var(--space-3);
  min-height: 52px;
}

.step-marker {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius-sm);
  color: var(--muted);
  font-size: var(--fs-xs);
}

.process-step[data-state='done'] .step-marker {
  border-color: var(--ok);
  color: var(--ok);
}

.process-step[data-state='current'] .step-marker {
  border-color: var(--accent);
  color: var(--accent);
}

.process-step[data-state='failed'] .step-marker {
  border-color: var(--risk);
  color: var(--risk);
}

.step-body {
  padding: 4px 0 var(--space-3);
  border-bottom: 1px solid var(--rule);
}

.process-step:last-child .step-body {
  border-bottom: 0;
}

.step-heading {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  color: var(--ink);
  font-size: var(--fs-sm);
}

.step-state {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.process-step[data-state='current'] .step-state {
  color: var(--accent);
}

.process-step[data-state='failed'] .step-state {
  color: var(--risk);
}

.chunk-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: var(--space-3) 0 0;
  padding: 0;
  list-style: none;
}

.chunk-list li {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--rule);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--ink-2);
  font-size: var(--fs-xs);
}

.chunk-phase {
  color: var(--accent);
}

.step-hint {
  margin: var(--space-2) 0 0;
}
</style>
