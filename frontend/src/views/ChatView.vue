<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import MarkdownIt from 'markdown-it'
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
const userStore = useUserStore()

const input = ref('')
const messages = ref<ChatMessage[]>([])
const loading = ref(false)
const conversationId = ref('')
const listRef = ref<HTMLElement | null>(null)

// 标注弹窗状态
const annotateVisible = ref(false)
const annotateTarget = ref<ChatMessage | null>(null)
const annotateQuestion = ref('')
const correctedContent = ref('')
const submitting = ref(false)
const lastFailedId = ref<number | null>(null)

function reset() {
  messages.value = [
    {
      role: 'assistant',
      content: '你好，我是企业合规智能助手。可以咨询差旅、接待、招采等环节的合规问题，我会依据公司制度作答并给出依据来源。',
    },
  ]
  conversationId.value = ''
}

async function scrollToBottom() {
  await nextTick()
  const el = listRef.value
  if (el) el.scrollTop = el.scrollHeight
}

async function send() {
  const query = input.value.trim()
  if (!query || loading.value) return

  messages.value.push({ role: 'user', content: query })
  messages.value.push({ role: 'assistant', content: '' })
  const idx = messages.value.length - 1
  input.value = ''
  loading.value = true
  await scrollToBottom()

  try {
    await chatStream(
      { query, conversation_id: conversationId.value },
      (event, payload) => {
        if (event === 'message') {
          const chunk = String(payload.answer ?? '')
          if (chunk) {
            messages.value[idx].content += chunk
            scrollToBottom()
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
    )
  } catch {
    if (!messages.value[idx].content) {
      messages.value[idx].content = '（本次回答失败，请重试）'
    }
  } finally {
    loading.value = false
    await scrollToBottom()
  }
}

function renderMarkdown(content: string) {
  return md.render(content)
}

/** 打开专家标注弹窗：带出该回答对应的提问与原回答 */
function openAnnotate(msg: ChatMessage, index: number) {
  annotateTarget.value = msg
  annotateQuestion.value = messages.value[index - 1]?.role === 'user' ? messages.value[index - 1].content : ''
  correctedContent.value = msg.correction ? '' : ''
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

onMounted(reset)
</script>

<template>
  <div class="chat-container reveal-group">
    <div class="toolbar">
      <span class="u-caption">问答记录</span>
      <el-button size="small" text @click="reset">新建会话</el-button>
    </div>

    <div ref="listRef" class="message-list">
      <div v-for="(msg, i) in messages" :key="i" class="message" :class="msg.role">
        <div class="body">
          <div v-if="!msg.content && loading && i === messages.length - 1" class="typing">
            正在检索知识库…
          </div>
          <template v-else>
            <div class="prose" v-html="renderMarkdown(msg.content)" /><span
              v-if="msg.role === 'assistant' && loading && i === messages.length - 1"
              class="stream-caret"
              aria-hidden="true"
            />
          </template>

          <!-- 依据来源：引注式列举，编号与相似度走等宽，便于逐条比对 -->
          <div v-if="msg.sources?.length" class="cites">
            <p class="cites-title u-caption">依据来源</p>
            <ol class="cites-list">
              <li v-for="(s, si) in msg.sources" :key="si" class="cite">
                <span class="cite-no u-num">{{ String(si + 1).padStart(2, '0') }}</span>
                <span class="cite-doc">{{ s.document_name || '未知来源' }}</span>
                <span v-if="s.segment_position" class="cite-meta u-num">
                  第 {{ s.segment_position }} 段
                </span>
                <span v-if="typeof s.score === 'number'" class="cite-meta u-num">
                  相似度 {{ s.score.toFixed(3) }}
                </span>
              </li>
            </ol>
          </div>

          <!-- 专家就地标注（需求⑤）：仅专家角色、且只针对真实回答（有 message_id）可见 -->
          <div
            v-if="userStore.isExpert && msg.role === 'assistant' && msg.messageId"
            class="annotate-bar"
          >
            <el-tag v-if="msg.correction?.writeStatus === 'written'" type="success" size="small">
              已标注
            </el-tag>
            <el-tag v-else-if="msg.correction" type="danger" size="small">标注待重试</el-tag>
            <el-button link type="primary" size="small" @click="openAnnotate(msg, i)">
              {{ msg.correction ? '继续标注' : '标注纠错' }}
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <div class="input-bar">
      <el-input
        v-model="input"
        type="textarea"
        :rows="3"
        placeholder="请输入你的问题，Ctrl+Enter 发送"
        @keydown.ctrl.enter.prevent="send"
      />
      <el-button type="primary" :loading="loading" @click="send">发送</el-button>
    </div>

    <!-- 专家标注弹窗：原回答只读展示，专家填写修正内容 -->
    <el-dialog v-model="annotateVisible" title="专家标注纠错" width="680px">
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

.toolbar {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--rule);
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-5) var(--space-5) var(--space-6);
}

.message {
  display: flex;
  margin-bottom: var(--space-4);
}

@media (prefers-reduced-motion: no-preference) {
  .message {
    animation: z-reveal var(--dur-base) var(--ease-out) both;
  }
}

/* 答复气泡：纸面卡片，左下角收角做气泡的「口」。
   行长用 em 限幅，避免宽屏下一行拉到五六十个汉字。 */
.message.assistant .body {
  max-width: min(78%, 46em);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--rule);
  border-radius: var(--radius-xl) var(--radius-xl) var(--radius-xl) var(--radius-sm);
  background: var(--surface);
}

/* 提问气泡：右侧深墨底，右下角收角。
   强调色留给别处，不让用户消息再抢一个颜色。 */
.message.user {
  justify-content: flex-end;
}

.message.user .body {
  max-width: min(78%, 34em);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-xl) var(--radius-xl) var(--radius-sm) var(--radius-xl);
  background: var(--ink);
  color: var(--paper);
}

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

.prose :deep(table) {
  width: 100%;
  margin: 0 0 var(--space-3);
  border-collapse: collapse;
  font-size: var(--fs-sm);
}

.prose :deep(th),
.prose :deep(td) {
  padding: var(--space-1) var(--space-3);
  border-bottom: 1px solid var(--rule);
  text-align: left;
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

.typing {
  color: var(--muted);
}

.cites {
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--rule-strong);
}

.cites-title {
  margin: 0 0 var(--space-2);
}

.cites-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.cite {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  flex-wrap: wrap;
  font-size: var(--fs-xs);
}

.cite-no {
  color: var(--muted);
}

.cite-doc {
  color: var(--ink-2);
}

.cite-meta {
  color: var(--muted);
}

.annotate-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

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

/* 输入区做成纸面之外的白色条带，与上方的问答记录分开 */
.input-bar {
  flex: none;
  display: flex;
  align-items: flex-end;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--rule);
  background: var(--surface);
}

.input-bar :deep(.el-textarea) {
  flex: 1;
  min-width: 0;
}
</style>
