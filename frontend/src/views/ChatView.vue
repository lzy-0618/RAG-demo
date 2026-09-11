<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { chatStream } from '@/api/chat'

const md = new MarkdownIt()
const input = ref('')
const messages = ref<Array<{ role: 'user' | 'assistant'; content: string }>>([])
const loading = ref(false)

async function send() {
  const query = input.value.trim()
  if (!query || loading.value) return
  messages.value.push({ role: 'user', content: query })
  input.value = ''
  loading.value = true
  // 占位，流式追加
  messages.value.push({ role: 'assistant', content: '' })
  const idx = messages.value.length - 1
  try {
    await chatStream({ query }, (_event, payload) => {
      if (payload.answer) {
        messages.value[idx].content += payload.answer
      } else if (payload.error) {
        ElMessage.error(payload.error)
      }
    })
  } catch (e) {
    ElMessage.error('请求失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

function renderMarkdown(content: string) {
  return md.render(content)
}

onMounted(() => {
  messages.value.push({
    role: 'assistant',
    content: '你好，我是企业合规智能助手，可以解答法规、规章制度与合同相关问题。',
  })
})
</script>

<template>
  <div class="chat-container">
    <div class="message-list">
      <div
        v-for="(msg, i) in messages"
        :key="i"
        class="message"
        :class="msg.role"
      >
        <div class="bubble" v-html="renderMarkdown(msg.content)" />
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
  </div>
</template>

<style scoped>
.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
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
  max-width: 70%;
  padding: 10px 14px;
  border-radius: 8px;
  background: #f2f3f5;
  line-height: 1.6;
}
.message.user .bubble {
  background: #409eff;
  color: #fff;
}
.input-bar {
  display: flex;
  gap: 12px;
  padding: 12px;
  border-top: 1px solid #eee;
}
</style>
