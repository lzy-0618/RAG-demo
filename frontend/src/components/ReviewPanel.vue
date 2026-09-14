<script setup lang="ts">
/** 审查面板：合同审查与规章制度审查共用（页面不同、审查类型不同）。 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadRawFile, UploadUserFile } from 'element-plus'
import { getReviewTask, submitReview } from '@/api/review'
import type { ReviewTaskOut } from '@/api/review'

const props = defineProps<{
  reviewType: 'contract' | 'regulation'
}>()

const inputMode = ref<'text' | 'file'>('text')
const content = ref('')
const fileList = ref<UploadUserFile[]>([])
const submitting = ref(false)
const task = ref<ReviewTaskOut | null>(null)

let pollTimer: number | undefined

const RISK_META: Record<string, { text: string; type: 'danger' | 'warning' | 'info' }> = {
  high: { text: '高风险', type: 'danger' },
  medium: { text: '中风险', type: 'warning' },
  low: { text: '低风险', type: 'info' },
}

const isRunning = computed(
  () => task.value?.status === 'pending' || task.value?.status === 'running',
)
const progress = computed(() => {
  const t = task.value
  if (!t?.total_chunks) return 0
  return Math.round(((t.completed_chunks + t.failed_chunks) / t.total_chunks) * 100)
})
const canSubmit = computed(() =>
  inputMode.value === 'text' ? content.value.trim().length > 0 : fileList.value.length > 0,
)

function onFileChange(_file: unknown, files: UploadUserFile[]) {
  fileList.value = files
}

async function onSubmit() {
  if (!canSubmit.value || submitting.value) {
    ElMessage.warning(inputMode.value === 'text' ? '请输入待审查文本' : '请选择待审查文件')
    return
  }
  submitting.value = true
  try {
    const file = fileList.value[0]?.raw as UploadRawFile | undefined
    const res = await submitReview({
      reviewType: props.reviewType,
      content: inputMode.value === 'text' ? content.value : undefined,
      file: inputMode.value === 'file' ? file : undefined,
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
  fileList.value = []
}

onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="review-panel">
    <el-card>
      <template #header>
        <span>提交待审查内容</span>
      </template>

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
          <el-upload
            drag
            :auto-upload="false"
            :limit="1"
            :file-list="fileList"
            :on-change="onFileChange"
            accept=".pdf,.docx,.md,.txt"
          >
            <div class="upload-tip">拖拽文件到此处，或点击选择</div>
            <div class="upload-hint">支持 PDF / DOCX / MD / TXT；长文档会自动分块逐块审查</div>
          </el-upload>
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
      <template #header>
        <div class="progress-header">
          <span>审查进度</span>
          <span class="hint">
            {{ task.status === 'completed' ? '已完成' : task.status === 'failed' ? '失败' : '进行中' }}
            · 已审查 {{ task.completed_chunks }}/{{ task.total_chunks }} 块
            <template v-if="task.failed_chunks">（失败 {{ task.failed_chunks }} 块）</template>
          </span>
        </div>
      </template>
      <el-progress :percentage="progress" :status="task.status === 'failed' ? 'exception' : undefined" />
      <div v-if="task.source_name" class="hint file-name">文件：{{ task.source_name }}</div>
    </el-card>

    <el-card v-if="task?.status === 'completed' && task.result" class="mt">
      <template #header>
        <div class="progress-header">
          <span>审查结论</span>
          <el-tag :type="task.result.is_compliant ? 'success' : 'danger'" size="small">
            {{ task.result.is_compliant ? '未发现风险' : `发现 ${task.result.risks.length} 处风险` }}
          </el-tag>
        </div>
      </template>

      <el-alert
        :title="task.result.summary"
        :type="task.result.is_compliant ? 'success' : 'warning'"
        :closable="false"
      />

      <div v-for="(risk, i) in task.result.risks" :key="i" class="risk-card">
        <div class="risk-head">
          <el-tag :type="RISK_META[risk.risk_level]?.type ?? 'info'" size="small">
            {{ RISK_META[risk.risk_level]?.text ?? risk.risk_level }}
          </el-tag>
          <span v-if="risk.location" class="location">{{ risk.location }}</span>
        </div>

        <div class="clause">{{ risk.clause }}</div>

        <div v-if="risk.violations.length" class="block">
          <div class="block-title">违反依据</div>
          <div v-for="(v, vi) in risk.violations" :key="vi" class="violation">
            <span class="law">{{ v.law_name }}<template v-if="v.article"> · {{ v.article }}</template></span>
            <span class="desc">{{ v.description }}</span>
          </div>
        </div>

        <div v-if="risk.reference_case" class="block">
          <div class="block-title">参考案例</div>
          <div class="case">
            <span class="case-name">{{ risk.reference_case.case_name }}</span>
            <span class="desc">{{ risk.reference_case.lesson }}</span>
          </div>
        </div>

        <div v-if="risk.suggestion" class="block">
          <div class="block-title">修改建议</div>
          <div class="suggestion">{{ risk.suggestion }}</div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.review-panel {
  height: 100%;
  overflow-y: auto;
  padding: 16px;
}
.mt {
  margin-top: 16px;
}
.actions {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.upload-tip {
  color: #606266;
}
.upload-hint {
  color: #909399;
  font-size: 12px;
  margin-top: 6px;
}
.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.hint {
  color: #909399;
  font-size: 13px;
}
.file-name {
  margin-top: 8px;
}
.risk-card {
  margin-top: 16px;
  padding: 12px 14px;
  border: 1px solid #ebeef5;
  border-left: 3px solid #f56c6c;
  border-radius: 6px;
}
.risk-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.location {
  color: #909399;
  font-size: 12px;
}
.clause {
  padding: 8px 10px;
  background: #fafafa;
  border-radius: 4px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.block {
  margin-top: 10px;
  font-size: 13px;
}
.block-title {
  color: #909399;
  margin-bottom: 4px;
}
.violation,
.case {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 0;
  border-bottom: 1px dashed #f0f0f0;
}
.law,
.case-name {
  color: #409eff;
}
.desc {
  color: #606266;
  line-height: 1.6;
}
.suggestion {
  color: #303133;
  line-height: 1.6;
}
</style>
