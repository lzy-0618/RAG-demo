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

const inputMode = ref<'text' | 'file'>('text')
const content = ref('')
const reviewFile = ref<File | null>(null)
const submitting = ref(false)
const task = ref<ReviewTaskOut | null>(null)

let pollTimer: number | undefined

const isRunning = computed(
  () => task.value?.status === 'pending' || task.value?.status === 'running',
)
const progress = computed(() => {
  const t = task.value
  if (!t?.total_chunks) return 0
  return Math.round(((t.completed_chunks + t.failed_chunks) / t.total_chunks) * 100)
})
const canSubmit = computed(() =>
  inputMode.value === 'text' ? content.value.trim().length > 0 : !!reviewFile.value,
)

async function onSubmit() {
  if (!canSubmit.value || submitting.value) {
    ElMessage.warning(inputMode.value === 'text' ? '请输入待审查文本' : '请选择待审查文件')
    return
  }
  submitting.value = true
  try {
    const res = await submitReview({
      reviewType: props.reviewType,
      content: inputMode.value === 'text' ? content.value : undefined,
      file: inputMode.value === 'file' ? (reviewFile.value ?? undefined) : undefined,
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

      <el-tabs v-model="inputMode">
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
          · 已审查 {{ task.completed_chunks }}/{{ task.total_chunks }} 块
          <template v-if="task.failed_chunks">（失败 {{ task.failed_chunks }} 块）</template>
        </span>
      </div>
      <el-progress
        :percentage="progress"
        :status="task.status === 'failed' ? 'exception' : undefined"
      />
      <p v-if="task.source_name" class="hint file-name">文件：{{ task.source_name }}</p>
    </el-card>

    <el-card v-if="task?.status === 'completed' && task.result" class="mt">
      <div class="sec-bar">
        <h2 class="sec-head flush">审查结论</h2>
        <span class="verdict" :class="task.result.is_compliant ? 'is-clear' : 'is-risk'">
          <span class="verdict-dot" aria-hidden="true" />
          {{ task.result.is_compliant ? '未发现风险' : `发现 ${task.result.risks.length} 处风险` }}
        </span>
      </div>

      <el-alert
        :title="task.result.summary"
        :type="task.result.is_compliant ? 'success' : 'warning'"
        :closable="false"
      />

      <!-- 风险条目按「批注卡」呈现，呈现细节见 RiskNote 组件 -->
      <RiskNote
        v-for="(risk, i) in task.result.risks"
        :key="i"
        :index="i"
        :level="risk.risk_level"
        :location="risk.location"
        :clause="risk.clause"
        :violations="risk.violations"
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
</style>
