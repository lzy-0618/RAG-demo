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
import { downloadAuthedFile } from '@/api/download'
import FlowSteps from '@/components/FlowSteps.vue'
import RiskNote from '@/components/RiskNote.vue'

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
 * - 撰写/修正阶段（phase=generating）：细粒度不可知，进度停在当前单元起点（文案提示进行中）；
 * - 合规审查阶段（phase=reviewing）：单元内按已审查块数占比推进。
 * 例如 max_rounds=3 时：首版写作 0~25% → 第 1 轮审查 → 25~50% → 第 2 轮 → 50~75% → 第 3 轮 → 100%。
 */
const unit = computed(() => 100 / ((task.value?.max_rounds ?? 3) + 1))
const phase = computed(() => task.value?.phase ?? 'generating')
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
const MAIN_STEPS = ['填写需求', '生成并确认大纲', '生成全文与合规审查']

/** 当前所处流程位置：已开始生成即进入第三步，仅有大纲则停在第二步 */
const mainStep = computed(() => (task.value ? 2 : outline.value ? 1 : 0))

/** 轮次编排线：首版 + 最多 max_rounds 轮修正 */
const roundSteps = computed(() => [
  '首版撰写',
  ...Array.from({ length: task.value?.max_rounds ?? 0 }, (_, i) => `第 ${i + 1} 轮修正`),
])

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
    await downloadAuthedFile(
      `/generate/files/${encodeURIComponent(task.value.doc_name)}`,
      task.value.doc_name,
    )
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : '下载失败')
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
  <div class="page reveal-group">
    <el-card>
      <!-- 页标题由外壳的文书头承担；这里用编排线直接表达流程 -->
      <FlowSteps :steps="MAIN_STEPS" :active="mainStep" class="flow-block" />

      <el-form label-position="top" class="form">
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
      <div class="sec-bar">
        <h2 class="sec-head flush">生成进度</h2>
        <span class="hint u-num">
          {{ phaseText }} · 修正轮次 {{ task.round }}/{{ task.max_rounds }}
        </span>
      </div>

      <!-- 统一使用一个进度条：按轮次推进（每完成一轮 +25%），撰写阶段停在当前单元起点 -->
      <el-progress
        :percentage="percentage"
        :status="task.status === 'failed' ? 'exception' : undefined"
      />

      <FlowSteps
        :steps="roundSteps"
        :active="task.round + (phase === 'done' ? 1 : 0)"
        class="rounds"
      />
    </el-card>

    <el-card v-if="task?.status === 'completed'" class="mt">
      <div class="sec-bar">
        <h2 class="sec-head flush">生成结果</h2>
        <span class="verdict" :class="task.is_compliant ? 'is-clear' : 'is-risk'">
          <span class="verdict-dot" aria-hidden="true" />
          {{ task.is_compliant ? '合规审查通过' : '仍有冲突，需人工复核' }}
        </span>
      </div>

      <el-alert
        :title="task.summary || ''"
        :type="task.is_compliant ? 'success' : 'warning'"
        :closable="false"
      />

      <!-- 审查发现的冲突按批注卡呈现，与审查页同一套语言 -->
      <RiskNote
        v-for="(risk, i) in task.review?.risks ?? []"
        :key="i"
        :index="i"
        :level="risk.risk_level"
        :location="risk.location"
        :clause="risk.clause"
        :violations="risk.violations"
        :analysis="risk.analysis"
        :citations="risk.citations"
        :needs-review="risk.needs_review"
        :validation-notes="risk.validation_notes"
        :suggestion="risk.suggestion"
      />

      <div class="sec-bar sections-bar">
        <h2 class="sec-head flush">正文</h2>
        <span class="hint u-num">{{ task.sections.length }} 章</span>
      </div>

      <div class="sections">
        <article v-for="(s, i) in task.sections" :key="i" class="section">
          <h3 class="section-title">
            <span class="section-no u-num">{{ String(i + 1).padStart(2, '0') }}</span>
            {{ s.title }}
          </h3>
          <p class="section-content">{{ s.content }}</p>
        </article>
      </div>

      <el-button type="primary" class="mt" @click="onDownload">下载 Word 文档</el-button>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  height: 100%;
  padding: var(--space-5);
  overflow-y: auto;
}

/* 区段头、状态标记、批注卡是跨页面复用版式，统一定义在 styles/patterns.css */
.flow-block {
  margin-bottom: var(--space-5);
}

.form {
  margin-top: 0;
}

.rounds {
  margin-top: var(--space-4);
}

.mt {
  margin-top: var(--space-5);
}

.sections-bar {
  margin-top: var(--space-6);
}

.sections {
  max-height: 46vh;
  overflow-y: auto;
}

.section {
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--rule);
}

.section:last-child {
  border-bottom: none;
}

.section-title {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  margin: 0 0 var(--space-2);
  font-family: var(--font-serif);
  font-size: var(--fs-md);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.45;
  color: var(--ink);
}

.section-no {
  font-size: var(--fs-2xs);
  font-weight: 400;
  color: var(--muted);
}

.section-content {
  margin: 0;
  font-size: var(--fs-md);
  line-height: var(--lh-base);
  color: var(--ink);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
