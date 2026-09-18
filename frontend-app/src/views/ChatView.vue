<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { Browser } from '@capacitor/browser'
import { ElMessage } from 'element-plus'
import MarkdownIt from 'markdown-it'
import AppIcon from '@/components/AppIcon.vue'
import { chatStream } from '@/api/chat'
import { createCorrection, retryCorrection } from '@/api/correction'
import { useUserStore } from '@/stores/user'

interface SourceItem {
  document_name?: string
  segment_position?: number
  score?: number
  content?: string
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: SourceItem[]
  /** Dify 消息 ID：专家标注需据此关联到具体回答 */
  messageId?: string
  /** 该回答对应的标注状态（专家已标注时展示） */
  correction?: { id: number; writeStatus: string }
}

const md = new MarkdownIt()
// markdown-it 默认吐裸 <table>，窄屏下宽表会撑破卡片，包一层可横滑的容器
const renderTableOpen = md.renderer.rules.table_open
md.renderer.rules.table_open = (tokens, idx, options, env, self) =>
  `<div class="table-wrap">${
    renderTableOpen ? renderTableOpen(tokens, idx, options, env, self) : self.renderToken(tokens, idx, options)
  }`
md.renderer.rules.table_close = (tokens, idx, options, _env, self) =>
  `${self.renderToken(tokens, idx, options)}</div>`

/** 手机打中文很累，首屏给几个可直接发出的问题。领域取自知识库里已有的审核规则文档。 */
const SAMPLE_QUESTIONS = [
  '差旅报销标准是什么？',
  '接待审批权限怎么规定？',
  '招采流程有哪些要求？',
]

const userStore = useUserStore()

const input = ref('')
const messages = ref<ChatMessage[]>([])
const loading = ref(false)
const conversationId = ref('')
const listRef = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLTextAreaElement | null>(null)

/** 是否贴在底部：只有在贴底时才自动跟随流式输出，往上翻历史不会被拽回去 */
const pinned = ref(true)
const copiedIdx = ref(-1)
let copyTimer = 0
let controller: AbortController | null = null

// 标注弹窗状态
const annotateVisible = ref(false)
const annotateTarget = ref<ChatMessage | null>(null)
const annotateQuestion = ref('')
const correctedContent = ref('')
const submitting = ref(false)
const lastFailedId = ref<number | null>(null)

const roundCount = computed(() => messages.value.filter((m) => m.role === 'user').length)
const showSamples = computed(() => roundCount.value === 0 && !loading.value)

function reset() {
  messages.value = [
    {
      role: 'assistant',
      content: '你好，我是企业合规智能助手。可以咨询差旅、接待、招采等环节的合规问题，我会依据公司制度作答并给出依据来源。',
    },
  ]
  conversationId.value = ''
  copiedIdx.value = -1
  pinned.value = true
  // 新会话不该带着上一轮的草稿
  input.value = ''
  void nextTick(() => {
    if (listRef.value) listRef.value.scrollTop = 0
    autoGrow()
  })
}

const isLastAssistant = (i: number) =>
  i === messages.value.length - 1 && messages.value[i]?.role === 'assistant'

/** 该条是否正在流式接收中 */
const isStreamingAt = (i: number) => loading.value && isLastAssistant(i)
const canAnnotate = (msg: ChatMessage) =>
  userStore.isExpert && msg.role === 'assistant' && Boolean(msg.messageId)
const showActions = (msg: ChatMessage, i: number) =>
  msg.role === 'assistant' && Boolean(msg.content) && !isStreamingAt(i)

function citeMeta(s: SourceItem) {
  const parts: string[] = []
  if (s.segment_position) parts.push(`第 ${s.segment_position} 段`)
  if (typeof s.score === 'number') parts.push(`相似度 ${s.score.toFixed(3)}`)
  return parts.join(' · ')
}

function onListScroll() {
  const el = listRef.value
  if (!el) return
  pinned.value = el.scrollHeight - el.scrollTop - el.clientHeight < 48
}

/** force 用于「发送」和「回到底部」；流式分片只在已贴底时跟随 */
async function followBottom(force = false) {
  if (!force && !pinned.value) return
  await nextTick()
  const el = listRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
  pinned.value = true
}

/** 输入框随内容增高，1 行起、最多 5 行（与 CSS 的 max-height 对应） */
const INPUT_MAX_HEIGHT = 140
function autoGrow() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, INPUT_MAX_HEIGHT)}px`
  el.style.overflowY = el.scrollHeight > INPUT_MAX_HEIGHT ? 'auto' : 'hidden'
}

/** clipboard API 在 WebView 里可能因权限缺失抛错，回退到临时 textarea 方案 */
async function copyText(text: string) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 落到下面的兜底实现
  }
  try {
    const el = document.createElement('textarea')
    el.value = text
    el.setAttribute('readonly', '')
    el.style.position = 'fixed'
    el.style.top = '-1000px'
    el.style.opacity = '0'
    document.body.appendChild(el)
    el.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(el)
    return ok
  } catch {
    return false
  }
}

/** 复制渲染后的纯文本：粘进 Word 不用再删 markdown 符号 */
async function copyAnswer(msg: ChatMessage, index: number, ev: MouseEvent) {
  const prose = (ev.currentTarget as HTMLElement | null)
    ?.closest('.body')
    ?.querySelector('.prose') as HTMLElement | null
  const ok = await copyText(prose?.innerText?.trim() || msg.content)
  if (!ok) {
    ElMessage.warning('复制失败')
    return
  }
  copiedIdx.value = index
  window.clearTimeout(copyTimer)
  copyTimer = window.setTimeout(() => {
    copiedIdx.value = -1
  }, 1500)
}

async function send() {
  const query = input.value.trim()
  if (!query || loading.value) return

  messages.value.push({ role: 'user', content: query })
  messages.value.push({ role: 'assistant', content: '' })
  const idx = messages.value.length - 1
  input.value = ''
  loading.value = true
  await followBottom(true)
  await nextTick()
  autoGrow()

  controller = new AbortController()
  try {
    await chatStream(
      { query, conversation_id: conversationId.value },
      (event, payload) => {
        if (event === 'message') {
          const chunk = String(payload.answer ?? '')
          if (chunk) {
            messages.value[idx].content += chunk
            void followBottom()
          }
        } else if (event === 'sources') {
          messages.value[idx].sources = (payload.sources as SourceItem[]) ?? []
        } else if (event === 'message_end') {
          if (payload.conversation_id) conversationId.value = String(payload.conversation_id)
          if (payload.message_id) messages.value[idx].messageId = String(payload.message_id)
        } else if (event === 'error') {
          ElMessage.error(String(payload.error ?? '对话失败'))
        }
      },
      controller.signal,
    )
  } catch (err) {
    const aborted = (err as Error | undefined)?.name === 'AbortError'
    const current = messages.value[idx]
    if (aborted) {
      current.content = current.content ? `${current.content}\n\n（已停止生成）` : '（已停止生成）'
    } else if (!current.content) {
      current.content = '（本次回答失败，请重试）'
    }
  } finally {
    controller = null
    loading.value = false
    await followBottom()
  }
}

function stop() {
  controller?.abort()
}

async function askSample(q: string) {
  if (loading.value) return
  input.value = q
  await send()
}

function renderMarkdown(content: string) {
  return md.render(content)
}

/** App 内 WebView 直接把 <a> 交给自己导航，会顶掉整个应用且无法返回；
 *  改为交给系统浏览器打开。 */
function onProseClick(e: MouseEvent) {
  const anchor = (e.target as HTMLElement | null)?.closest('a')
  const href = anchor?.getAttribute('href')
  if (!href || !/^https?:\/\//i.test(href)) return
  e.preventDefault()
  void Browser.open({ url: href })
}

/** 打开专家标注弹窗：带出该回答对应的提问与原回答 */
function openAnnotate(msg: ChatMessage, index: number) {
  annotateTarget.value = msg
  annotateQuestion.value = messages.value[index - 1]?.role === 'user' ? messages.value[index - 1].content : ''
  correctedContent.value = ''
  lastFailedId.value = null
  annotateVisible.value = true
}

async function submitAnnotation() {
  const target = annotateTarget.value
  if (!target) return
  if (!correctedContent.value.trim()) {
    ElMessage.warning('请输入修正后的内容')
    return
  }
  submitting.value = true
  try {
    const res = await createCorrection({
      source_content: target.content,
      corrected_content: correctedContent.value,
      question: annotateQuestion.value || null,
      conversation_id: conversationId.value || null,
      message_id: target.messageId || null,
    })
    target.correction = { id: res.data.id, writeStatus: res.data.write_status }
    if (res.data.write_status === 'written') {
      ElMessage.success('标注已提交并写入专家知识库')
      annotateVisible.value = false
      correctedContent.value = ''
    } else {
      lastFailedId.value = res.data.id
      ElMessage.warning('标注已保存，但写入知识库失败，可重试')
    }
  } finally {
    submitting.value = false
  }
}

/** 写库失败重试 */
async function retryAnnotation() {
  if (!lastFailedId.value) return
  submitting.value = true
  try {
    const res = await retryCorrection(lastFailedId.value)
    if (res.data.write_status === 'written') {
      if (annotateTarget.value) {
        annotateTarget.value.correction = { id: res.data.id, writeStatus: 'written' }
      }
      ElMessage.success('重试成功，已写入专家知识库')
      annotateVisible.value = false
      correctedContent.value = ''
      lastFailedId.value = null
    } else {
      ElMessage.error(res.data.error || '重试仍失败')
    }
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  reset()
  autoGrow()
})

onBeforeUnmount(() => {
  window.clearTimeout(copyTimer)
  controller?.abort()
})
</script>

<template>
  <div class="chat-container reveal-group">
    <div class="toolbar">
      <span class="session-state">
        <span class="session-dot" :class="{ 'is-live': roundCount > 0 }" aria-hidden="true" />
        {{ roundCount > 0 ? `本次会话 · ${roundCount} 轮` : '新会话' }}
      </span>
      <button type="button" class="new-session" @click="reset">
        <AppIcon name="plus" :size="15" />
        <span>新建会话</span>
      </button>
    </div>

    <div class="message-area">
      <div ref="listRef" class="message-list" @scroll.passive="onListScroll">
        <div
          v-for="(msg, i) in messages"
          :key="i"
          class="message"
          :class="[msg.role, { 'is-streaming': isStreamingAt(i) }]"
        >
          <div class="body">
            <div v-if="isStreamingAt(i) && !msg.content" class="typing">
              <span class="dot" /><span class="dot" /><span class="dot" />
              <span class="typing-text">正在检索知识库…</span>
            </div>
            <template v-else>
              <div class="prose" v-html="renderMarkdown(msg.content)" @click="onProseClick" /><span
                v-if="isStreamingAt(i)"
                class="stream-caret"
                aria-hidden="true"
              />
            </template>

            <!-- 依据来源：账目式列举，编号与相似度走等宽，行间发丝线分隔 -->
            <div v-if="msg.sources?.length" class="cites">
              <p class="cites-title u-caption">依据来源</p>
              <ol class="cites-list">
                <li v-for="(s, si) in msg.sources" :key="si" class="cite">
                  <span class="cite-no u-num">{{ String(si + 1).padStart(2, '0') }}</span>
                  <span class="cite-main">
                    <span class="cite-doc">{{ s.document_name || '未知来源' }}</span>
                    <span v-if="citeMeta(s)" class="cite-meta u-num">{{ citeMeta(s) }}</span>
                  </span>
                </li>
              </ol>
            </div>

            <!-- 回答就绪后才出操作条：复制对合规条文很常用 -->
            <div v-if="showActions(msg, i)" class="msg-actions">
              <button
                type="button"
                class="act"
                :class="{ 'is-done': copiedIdx === i }"
                @click="copyAnswer(msg, i, $event)"
              >
                <AppIcon :name="copiedIdx === i ? 'check' : 'copy'" :size="15" />
                <span>{{ copiedIdx === i ? '已复制' : '复制' }}</span>
              </button>

              <!-- 专家就地标注（需求⑤）：仅专家角色、且只针对真实回答（有 message_id）可见 -->
              <template v-if="canAnnotate(msg)">
                <span v-if="msg.correction?.writeStatus === 'written'" class="badge badge--ok">
                  已标注
                </span>
                <span v-else-if="msg.correction" class="badge badge--risk">标注待重试</span>
                <button type="button" class="act" @click="openAnnotate(msg, i)">
                  <span>{{ msg.correction ? '继续标注' : '标注纠错' }}</span>
                </button>
              </template>
            </div>
          </div>
        </div>

        <!-- 首屏引导：点一下直接发出，省去在手机上打中文 -->
        <div v-if="showSamples" class="samples">
          <p class="samples-title u-caption">可以这样问</p>
          <button
            v-for="q in SAMPLE_QUESTIONS"
            :key="q"
            type="button"
            class="sample"
            @click="askSample(q)"
          >
            {{ q }}
          </button>
        </div>
      </div>

      <button v-if="!pinned" type="button" class="to-bottom" @click="followBottom(true)">
        <AppIcon name="down" :size="16" />
        <span class="sr-only">回到底部</span>
      </button>
    </div>

    <div class="composer">
      <div class="composer-field">
        <textarea
          ref="inputRef"
          v-model="input"
          class="composer-input"
          rows="1"
          placeholder="输入你的问题…"
          @input="autoGrow"
          @keydown.ctrl.enter.prevent="send"
        />
        <button
          type="button"
          class="composer-send"
          :class="{ 'is-stop': loading }"
          :disabled="!loading && !input.trim()"
          :aria-label="loading ? '停止生成' : '发送'"
          @click="loading ? stop() : send()"
        >
          <AppIcon :name="loading ? 'stop' : 'send'" :size="20" />
        </button>
      </div>
    </div>

    <!-- 专家标注弹窗：原回答只读展示，专家填写修正内容 -->
    <el-dialog v-model="annotateVisible" title="专家标注纠错" width="min(680px, 92vw)">
      <div class="annotate-block">
        <div class="annotate-label">用户问题</div>
        <div class="annotate-text">{{ annotateQuestion || '（未记录）' }}</div>
      </div>
      <div class="annotate-block">
        <div class="annotate-label">原 AI 回答（被纠错内容）</div>
        <div class="annotate-text">{{ annotateTarget?.content || '' }}</div>
      </div>
      <div class="annotate-block">
        <div class="annotate-label">专家修正内容（将写入专家知识库，后续回答以此为参考）</div>
        <el-input
          v-model="correctedContent"
          type="textarea"
          :rows="6"
          placeholder="请填写正确、完整的表述"
        />
      </div>
      <template #footer>
        <el-button @click="annotateVisible = false">取消</el-button>
        <el-button v-if="lastFailedId" :loading="submitting" @click="retryAnnotation">
          重试写入知识库
        </el-button>
        <el-button type="primary" :loading="submitting" @click="submitAnnotation">提交标注</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
}

/* ---------- 会话状态条 ---------- */
.toolbar {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--rule);
}

.session-state {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  letter-spacing: 0.06em;
  color: var(--muted);
}

.session-dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-pill);
  background: var(--rule-strong);
}

.session-dot.is-live {
  background: var(--accent);
}

.new-session {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  height: 30px;
  padding: 0 var(--space-3);
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--ink-2);
  font: inherit;
  font-size: var(--fs-2xs);
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.new-session:active {
  border-color: var(--accent);
  color: var(--accent);
}

/* ---------- 消息区 ---------- */
.message-area {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
}

.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-4) var(--space-4) var(--space-6);
}

.message {
  display: flex;
}

@media (prefers-reduced-motion: no-preference) {
  .message {
    animation: z-reveal var(--dur-base) var(--ease-out) both;
  }
}

/* 答复：通栏纸面卡片，左侧引注线对齐 .annotate-text 的语言。
   引注线在流式生成时转为朱红——全屏只有这一处会用掉强调色。 */
.message.assistant .body {
  width: 100%;
  max-width: 46em;
  padding: var(--space-4);
  border: 1px solid var(--rule);
  border-left: 2px solid var(--rule-strong);
  border-radius: var(--radius-lg);
  background: var(--surface);
  transition: border-left-color var(--dur-base) var(--ease-out);
}

.message.assistant + .message.assistant {
  margin-top: var(--space-3);
}

.message.assistant.is-streaming .body {
  border-left-color: var(--accent);
}

/* 提问：右侧深墨气泡，右下角收角做气泡的「口」 */
.message.user {
  justify-content: flex-end;
  margin-top: var(--space-4);
}

.message.user .body {
  max-width: min(85%, 34em);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-xl) var(--radius-xl) var(--radius-sm) var(--radius-xl);
  background: var(--ink);
  color: var(--paper);
}

/* ---------- 正文排版 ---------- */
.prose {
  line-height: var(--lh-base);
  word-break: break-word;
}

.prose :deep(p) {
  margin: 0 0 var(--space-3);
}

.prose :deep(p:last-child) {
  margin-bottom: 0;
}

.prose :deep(ul),
.prose :deep(ol) {
  margin: 0 0 var(--space-3);
  padding-left: 1.5em;
}

.prose :deep(li) {
  margin-bottom: var(--space-1);
}

.prose :deep(strong) {
  font-weight: 600;
}

.prose :deep(a) {
  color: var(--accent);
}

.prose :deep(blockquote) {
  margin: 0 0 var(--space-3);
  padding-left: var(--space-4);
  border-left: 2px solid var(--rule-strong);
  color: var(--ink-2);
}

.prose :deep(pre) {
  margin: 0 0 var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--rule);
  border-radius: var(--radius-md);
  background: var(--surface-2);
  font-size: var(--fs-sm);
  overflow-x: auto;
}

.prose :deep(code) {
  font-size: 0.92em;
}

.prose :deep(pre code) {
  font-size: inherit;
}

/* base.css 把 h1-h4 定成 31/25/20/17px 的宋体大标题，那是给整页文档用的；
   回答正文里的标题必须收敛，否则一个 ## 会在卡片里撑出 25px 的字 */
.prose :deep(h1),
.prose :deep(h2) {
  margin: var(--space-4) 0 var(--space-2);
  font-family: var(--font-serif);
  font-size: var(--fs-lg);
  font-weight: 600;
  letter-spacing: var(--tracking-display);
  line-height: 1.35;
}

.prose :deep(h3),
.prose :deep(h4) {
  margin: var(--space-3) 0 var(--space-2);
  font-size: var(--fs-md);
  font-weight: 600;
}

.prose :deep(h1:first-child),
.prose :deep(h2:first-child),
.prose :deep(h3:first-child) {
  margin-top: 0;
}

.prose :deep(hr) {
  margin: var(--space-4) 0;
  border: 0;
  border-top: 1px solid var(--rule);
}

/* 宽表横滑，不撑破卡片 */
.prose :deep(.table-wrap) {
  margin: 0 0 var(--space-3);
  overflow-x: auto;
}

.prose :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-sm);
}

.prose :deep(th),
.prose :deep(td) {
  padding: var(--space-1) var(--space-3);
  border-bottom: 1px solid var(--rule);
  text-align: left;
  white-space: nowrap;
}

/* 深墨气泡里，正文内的代码块/引用/链接要换一套浅色，否则会变成深底压深底 */
.message.user .prose :deep(a) {
  color: var(--accent-wash);
}

.message.user .prose :deep(code),
.message.user .prose :deep(pre) {
  border-color: rgba(250, 248, 245, 0.22);
  background: rgba(250, 248, 245, 0.12);
  color: var(--paper);
}

.message.user .prose :deep(blockquote) {
  border-left-color: rgba(250, 248, 245, 0.32);
  color: var(--paper);
}

.message.user .prose :deep(th),
.message.user .prose :deep(td) {
  border-bottom-color: rgba(250, 248, 245, 0.2);
}

/* ---------- 检索中 ---------- */
.typing {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--muted);
  font-size: var(--fs-sm);
}

.dot {
  width: 5px;
  height: 5px;
  border-radius: var(--radius-pill);
  background: var(--accent);
  opacity: 0.3;
}

@media (prefers-reduced-motion: no-preference) {
  .dot {
    animation: z-pulse 1.2s ease-in-out infinite;
  }

  .dot:nth-child(2) {
    animation-delay: 0.16s;
  }

  .dot:nth-child(3) {
    animation-delay: 0.32s;
  }
}

@keyframes z-pulse {
  0%,
  100% {
    opacity: 0.25;
    transform: translateY(0);
  }

  50% {
    opacity: 1;
    transform: translateY(-2px);
  }
}

/* ---------- 依据来源 ---------- */
.cites {
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--rule-strong);
}

.cites-title {
  margin: 0 0 var(--space-2);
}

.cites-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.cite {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--rule);
}

.cite:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.cite-no {
  flex: none;
  font-size: var(--fs-2xs);
  color: var(--muted);
}

.cite-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.cite-doc {
  font-size: var(--fs-xs);
  color: var(--ink-2);
  word-break: break-all;
}

.cite-meta {
  font-size: var(--fs-2xs);
  color: var(--muted);
}

/* ---------- 回答操作条 ---------- */
.msg-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding-top: var(--space-2);
  border-top: 1px solid var(--rule);
}

.act {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  height: 28px;
  padding: 0 var(--space-2);
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: var(--fs-2xs);
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.act:active {
  background: var(--accent-wash);
  color: var(--accent);
}

.act.is-done {
  color: var(--ok);
}

.badge {
  padding: 1px var(--space-2);
  border: 1px solid currentColor;
  border-radius: var(--radius-sm);
  font-size: var(--fs-2xs);
}

.badge--ok {
  color: var(--ok);
}

.badge--risk {
  color: var(--risk);
}

/* ---------- 首屏引导问题 ---------- */
.samples {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
  margin-top: var(--space-5);
  padding-left: 2px;
}

.samples-title {
  margin: 0 0 var(--space-1);
}

.sample {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--ink-2);
  font: inherit;
  font-size: var(--fs-xs);
  text-align: left;
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.sample:active {
  border-color: var(--accent);
  color: var(--accent);
}

/* ---------- 回到底部 ---------- */
.to-bottom {
  position: absolute;
  right: var(--space-4);
  bottom: var(--space-4);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: var(--radius-pill);
  /* 压在白色回答卡片上时，白底圆钮几乎看不出来，改用墨色 */
  background: var(--ink);
  color: var(--paper);
  box-shadow: var(--shadow-2);
  cursor: pointer;
}

/* ---------- 输入区 ---------- */
.composer {
  flex: none;
  padding: var(--space-3) var(--space-4) var(--space-4);
  border-top: 1px solid var(--rule);
  background: var(--surface);
}

.composer-field {
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-1) var(--space-1) var(--space-4);
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius-xl);
  background: var(--paper);
  transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out);
}

.composer-field:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-wash);
}

.composer-input {
  flex: 1;
  min-width: 0;
  /* 与脚本里的 INPUT_MAX_HEIGHT 一致 */
  max-height: 140px;
  padding: var(--space-2) 0;
  border: 0;
  background: transparent;
  color: var(--ink);
  font: inherit;
  /* 16px 是 Android 不触发聚焦自动缩放的下限；行高与 autoGrow 的换算一致 */
  font-size: 16px;
  line-height: 24px;
  resize: none;
  outline: none;
  overflow-y: hidden;
}

.composer-input::placeholder {
  color: var(--placeholder);
}

.composer-send {
  flex: none;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border: 0;
  border-radius: var(--radius-pill);
  background: var(--accent);
  color: var(--on-accent);
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}

.composer-send:active {
  transform: scale(0.94);
  background: var(--accent-press);
}

.composer-send:disabled {
  background: var(--rule);
  color: var(--surface);
  cursor: not-allowed;
}

.composer-send.is-stop {
  background: var(--ink);
  color: var(--paper);
}

/* ---------- 专家标注弹窗 ---------- */
.annotate-block {
  margin-bottom: var(--space-3);
}

.annotate-label {
  margin: 0 0 var(--space-1);
  font-size: var(--fs-xs);
  color: var(--muted);
}

.annotate-text {
  max-height: 200px;
  padding: var(--space-2) var(--space-3);
  border-left: 2px solid var(--rule-strong);
  border-radius: var(--radius-md);
  background: var(--surface-2);
  font-size: var(--fs-sm);
  line-height: var(--lh-base);
  white-space: pre-wrap;
  word-break: break-word;
  overflow-y: auto;
}
</style>
