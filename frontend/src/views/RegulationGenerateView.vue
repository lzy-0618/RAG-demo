<script setup lang="ts">
/** 规章制度生成（需求⑧）：需求 → 大纲（可编辑确认）→ 全文 → 自动合规审查与修正循环 → 下载。 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  generateRegulationDocument,
  generateRegulationOutline,
  getRegulationTask,
} from '@/api/generate'
import type { GenerationTaskOut } from '@/api/generate'
import { downloadGeneratedFile } from '@/api/template'

const requirement = ref('')
const outline = ref('')
const outlineLoading = ref(false)
const submitting = ref(false)
const task = ref<GenerationTaskOut | null>(null)

let pollTimer: number | undefined

const running = computed(() => task.value?.status === 'pending' || task.value?.status === 'running')

/**
 * 整体进度按「轮次」推进，让用户对长流程有连续的体感：
 * 首版 + 最多 max_rounds 轮修正视为 (max_rounds + 1) 个单元，每完成一轮推进一个单元。
 * - 撰写/修正阶段（phase=generating）：单元内的细粒度不可知，用动效进度条表示进行中；
 * - 合规审查阶段（phase=reviewing）：单元内按已审查块数占比推进。
 * 例如 max_rounds=3 时：首版写作 0~25% → 第 1 轮审查 → 25~50% → 第 2 轮 → 50~75% → 第 3 轮 → 100%。
 */
const unit = computed(() => 100 / ((task.value?.max_rounds ?? 3) + 1))
const phase = computed(() => task.value?.phase ?? 'generating')
const isWriting = computed(() => running.value && phase.value === 'generating')

const percentage = computed(() => {
  const t = task.value
  if (!t) return 0
  if (t.status === 'completed') return 100
  if (t.status === 'failed') return Math.round((t.round || 0) * unit.value)
  const base = (t.round || 0) * unit.value
  if (t.phase === 'reviewing' && t.total_chunks) {
    const done = (t.completed_chunks || 0) + (t.failed_chunks || 0)
    return Math.min(99, Math.round(base + (done / t.total_chunks) * unit.value))
  }
  // 生成阶段：停在当前单元的起点（配动效条表示进行中）
  return Math.round(base)
})

/** 进度文案：区分「撰写/修正」与「审查第 N 轮」 */
const phaseText = computed(() => {
  const t = task.value
  if (!t) return ''
  if (t.status === 'completed') return '已完成'
  if (t.status === 'failed') return '失败'
  if (t.phase === 'reviewing') {
    const done = (t.completed_chunks || 0) + (t.failed_chunks || 0)
    return `第 ${t.review_round || 1} 轮合规审查中（${done}/${t.total_chunks || '?'} 块）`
  }
  return t.round > 0 ? `正在按审查意见修正（第 ${t.round} 轮）…` : '正在撰写全文…'
})
const RISK_META: Record<string, { text: string; type: 'danger' | 'warning' | 'info' }> = {
  high: { text: '高风险', type: 'danger' },
  medium: { text: '中风险', type: 'warning' },
  low: { text: '低风险', type: 'info' },
}

async function onGenerateOutline() {
  if (!requirement.value.trim()) {
    ElMessage.warning('请先填写规章制度的内容需求')
    return
  }
  outlineLoading.value = true
  try {
    const res = await generateRegulationOutline(requirement.value)
    outline.value = res.data.outline_text
    ElMessage.success('大纲已生成，可编辑确认后再生成全文')
  } finally {
    outlineLoading.value = false
  }
}

async function onGenerateDocument() {
  if (!requirement.value.trim() || !outline.value.trim()) {
    ElMessage.warning('需求与大纲都不能为空')
    return
  }
  submitting.value = true
  try {
    const res = await generateRegulationDocument(requirement.value, outline.value)
    task.value = null
    ElMessage.success('已提交生成，正在撰写全文并做合规审查')
    startPolling(res.data.task_id)
  } finally {
    submitting.value = false
  }
}

async function poll(taskId: number) {
  const res = await getRegulationTask(taskId)
  task.value = res.data
  if (res.data.status === 'completed' || res.data.status === 'failed') {
    stopPolling()
    if (res.data.status === 'failed') {
      ElMessage.error(res.data.error || '生成失败')
    } else if (res.data.is_compliant) {
      ElMessage.success('生成完成，合规审查未发现问题')
    } else {
      ElMessage.warning('生成完成，合规审查仍发现冲突，请人工复核')
    }
  }
}

function startPolling(taskId: number) {
  stopPolling()
  poll(taskId)
  pollTimer = window.setInterval(() => poll(taskId), 2000)
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

async function onDownload() {
  if (!task.value?.doc_name) return
  try {
    await downloadGeneratedFile(task.value.doc_name)
  } catch {
    ElMessage.error('下载失败')
  }
}

function reset() {
  stopPolling()
  task.value = null
  outline.value = ''
  requirement.value = ''
}

onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>规章制度生成</span>
          <span class="hint">需求 → 大纲（可修改）→ 全文 → 自动合规审查（不合规自动修正，最多 3 轮）</span>
        </div>
      </template>

      <el-steps :active="task?.status === 'completed' ? 3 : outline ? 2 : 1" simple class="steps">
        <el-step title="填写需求" />
        <el-step title="生成并确认大纲" />
        <el-step title="生成全文与合规审查" />
      </el-steps>

      <el-form label-position="top">
        <el-form-item label="内容需求">
          <el-input
            v-model="requirement"
            type="textarea"
            :rows="3"
            placeholder="如：制定一份差旅费管理办法，明确出差审批、住宿与交通标准、费用报销流程"
          />
        </el-form-item>
        <el-form-item>
          <el-button :loading="outlineLoading" @click="onGenerateOutline">生成大纲</el-button>
          <el-button
            type="primary"
            :loading="submitting || running"
            :disabled="!outline || running"
            class="ml"
            @click="onGenerateDocument"
          >
            {{ running ? '生成中…' : '确认大纲并生成全文' }}
          </el-button>
          <el-button text @click="reset">清空</el-button>
        </el-form-item>
        <el-form-item v-if="outline" label="大纲（可编辑后再生成全文）">
          <el-input v-model="outline" type="textarea" :rows="12" />
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="task" class="mt">
      <template #header>
        <div class="card-header">
          <span>生成进度</span>
          <span class="hint">
            {{ phaseText }} · 修正轮次 {{ task.round }}/{{ task.max_rounds }}
          </span>
        </div>
      </template>

      <!-- 撰写/修正阶段：细粒度不可知，用动效条表示「进行中」，避免进度条长时间停在 0 -->
      <div v-if="isWriting" class="writing-bar">
        <div class="writing-fill" />
      </div>
      <el-progress
        v-else
        :percentage="percentage"
        :status="task.status === 'failed' ? 'exception' : undefined"
      />

      <el-steps :active="task.round + (phase === 'done' ? 1 : 0)" simple class="sub-steps">
        <el-step title="首版撰写" />
        <el-step v-for="r in task.max_rounds" :key="r" :title="`第 ${r} 轮修正`" />
      </el-steps>
    </el-card>

    <el-card v-if="task?.status === 'completed'" class="mt">
      <template #header>
        <div class="card-header">
          <span>生成结果</span>
          <el-tag :type="task.is_compliant ? 'success' : 'danger'" size="small">
            {{ task.is_compliant ? '合规审查通过' : '仍有冲突，需人工复核' }}
          </el-tag>
        </div>
      </template>

      <el-alert :title="task.summary || ''" :type="task.is_compliant ? 'success' : 'warning'" :closable="false" />

      <div v-if="task.review?.risks?.length" class="risks">
        <div v-for="(risk, i) in task.review.risks" :key="i" class="risk">
          <el-tag :type="RISK_META[risk.risk_level]?.type ?? 'info'" size="small">
            {{ RISK_META[risk.risk_level]?.text ?? risk.risk_level }}
          </el-tag>
          <div class="clause">{{ risk.clause }}</div>
          <div v-for="(v, vi) in risk.violations" :key="vi" class="violation">
            {{ v.law_name }}<template v-if="v.article"> · {{ v.article }}</template>：{{ v.description }}
          </div>
          <div v-if="risk.suggestion" class="suggestion">建议：{{ risk.suggestion }}</div>
        </div>
      </div>

      <el-divider content-position="left">正文（{{ task.sections.length }} 章）</el-divider>
      <div class="sections">
        <div v-for="(s, i) in task.sections" :key="i" class="section">
          <div class="section-title">{{ s.title }}</div>
          <div class="section-content">{{ s.content }}</div>
        </div>
      </div>

      <el-button type="primary" class="mt" @click="onDownload">下载 Word 文档</el-button>
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
}
.steps {
  margin-bottom: 16px;
}
/* 撰写/修正阶段的动效进度条：斜纹循环滑动，表示「进行中且耗时不可预估」 */
.writing-bar {
  height: 6px;
  border-radius: 3px;
  background: #ebeef5;
  overflow: hidden;
}
.writing-fill {
  height: 100%;
  width: 40%;
  border-radius: 3px;
  background: repeating-linear-gradient(
    115deg,
    #a0cfff 0,
    #a0cfff 10px,
    #409eff 10px,
    #409eff 20px
  );
  animation: writing-slide 1.2s linear infinite;
}
@keyframes writing-slide {
  from {
    transform: translateX(-40%);
  }
  to {
    transform: translateX(250%);
  }
}
.sub-steps {
  margin-top: 12px;
}
.ml {
  margin-left: 10px;
}
.mt {
  margin-top: 16px;
}
.risks {
  margin-top: 14px;
}
.risk {
  padding: 10px 12px;
  border: 1px solid #f0f0f0;
  border-left: 3px solid #f56c6c;
  border-radius: 6px;
  margin-bottom: 10px;
}
.clause {
  margin: 6px 0;
  line-height: 1.6;
  white-space: pre-wrap;
}
.violation {
  color: #606266;
  font-size: 13px;
  line-height: 1.7;
}
.suggestion {
  margin-top: 4px;
  font-size: 13px;
  color: #303133;
}
.sections {
  max-height: 420px;
  overflow-y: auto;
}
.section {
  margin-bottom: 12px;
}
.section-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.section-content {
  color: #303133;
  line-height: 1.7;
  white-space: pre-wrap;
}
</style>
