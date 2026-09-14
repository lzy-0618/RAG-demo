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
  <div class="chat-container">
    <div class="toolbar">
      <el-button size="small" text @click="reset">新建会话</el-button>
    </div>

    <div ref="listRef" class="message-list">
      <div v-for="(msg, i) in messages" :key="i" class="message" :class="msg.role">
        <div class="bubble">
          <div v-if="!msg.content && loading && i === messages.length - 1" class="typing">
            正在检索知识库…
          </div>
          <div v-else v-html="renderMarkdown(msg.content)" />
          <div v-if="msg.sources?.length" class="sources">
            <div class="sources-title">依据来源</div>
            <div v-for="(s, si) in msg.sources" :key="si" class="source-item">
              <span class="doc">{{ s.document_name || '未知来源' }}</span>
              <span v-if="s.segment_position" class="pos">第 {{ s.segment_position }} 段</span>
              <span v-if="typeof s.score === 'number'" class="score">
                相似度 {{ s.score.toFixed(3) }}
              </span>
            </div>
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
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid #eee;
}
.toolbar .label {
  color: #606266;
  font-size: 13px;
}
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.message {
  margin-bottom: 12px;
  display: flex;
}
.message.user {
  justify-content: flex-end;
}
.bubble {
  max-width: 74%;
  padding: 10px 14px;
  border-radius: 8px;
  background: #f2f3f5;
  line-height: 1.6;
  word-break: break-word;
}
.message.user .bubble {
  background: #409eff;
  color: #fff;
}
.message.user .bubble :deep(p) {
  margin: 0;
}
.typing {
  color: #909399;
}
.sources {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #dcdfe6;
  font-size: 12px;
  color: #606266;
}
.sources-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.source-item {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.source-item .doc {
  color: #409eff;
}
.source-item .pos,
.source-item .score {
  color: #909399;
}
.annotate-bar {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.annotate-block {
  margin-bottom: 12px;
}
.annotate-label {
  color: #909399;
  font-size: 13px;
  margin-bottom: 4px;
}
.annotate-text {
  padding: 8px 10px;
  background: #fafafa;
  border-radius: 4px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
}
.input-bar {
  display: flex;
  gap: 12px;
  padding: 12px;
  border-top: 1px solid #eee;
}
</style>
