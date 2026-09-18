<script setup lang="ts">
/** 文件投放区：空态是可投放的虚线区，选中后收成一张文件卡（模板导入与审查共用）。
 *
 * 两态共用一个投放目标——已选之后整张卡片仍然接受点击与拖放，所以"换一个文件"
 * 不需要额外的按钮，界面里也就不会同时出现"虚线框"和"文件列表"两套东西。
 *
 * 文案里的格式清单由 accept 推导，避免提示与实际校验各说各话。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { formatFileSize } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    /** 传给 input 的 accept，同时用于推导提示文案与落地校验 */
    accept: string
    /** 次文案，补充限制条件（大小上限等） */
    hint?: string
  }>(),
  { hint: '' },
)

const file = defineModel<File | null>({ default: null })

const inputRef = ref<HTMLInputElement>()
const dragging = ref(false)

/** 拖拽进入/离开会在子元素间反复触发，用计数抵消，否则边框状态会闪 */
let dragDepth = 0

const extensions = computed(() =>
  props.accept
    .split(',')
    .map((item) => item.trim().toLowerCase())
    .filter((item) => item.startsWith('.')),
)
const formats = computed(() => extensions.value.join(' / '))
const sizeText = computed(() => (file.value ? formatFileSize(file.value.size) : ''))

function selectFile(candidate: File | undefined) {
  if (!candidate) return
  // 拖放不受 input 的 accept 约束，必须在这里拦一次，否则错误类型会一路走到后端
  if (extensions.value.length && !extensions.value.some((ext) => candidate.name.toLowerCase().endsWith(ext))) {
    ElMessage.error(`仅支持 ${formats.value} 格式，请重新选择`)
    return
  }
  file.value = candidate
}

function openPicker() {
  inputRef.value?.click()
}

function onPicked(event: Event) {
  const input = event.target as HTMLInputElement
  selectFile(input.files?.[0])
  // 清空 value：否则再次选中同一个文件不会触发 change，就换不掉了
  input.value = ''
}

function onDragEnter() {
  dragDepth += 1
  dragging.value = true
}

function onDragLeave() {
  dragDepth = Math.max(0, dragDepth - 1)
  if (dragDepth === 0) dragging.value = false
}

function onDrop(event: DragEvent) {
  dragDepth = 0
  dragging.value = false
  selectFile(event.dataTransfer?.files?.[0])
}
</script>

<template>
  <div
    class="drop"
    :class="{ 'is-filled': !!file, 'is-dragging': dragging }"
    @dragenter.prevent="onDragEnter"
    @dragover.prevent
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
  >
    <input ref="inputRef" class="drop__input" type="file" :accept="accept" @change="onPicked" />

    <button v-if="!file" class="drop__cta" type="button" @click="openPicker">
      <!-- 公文纸 + 折角：这里放的是合同/制度文件，不用通用的"云上传"符号 -->
      <svg
        class="drop__icon"
        viewBox="0 0 24 24"
        width="30"
        height="30"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
        focusable="false"
      >
        <path d="M13.5 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7.5z" />
        <path d="M13.5 3v4.5H18" />
        <path d="M8.5 12.5h7M8.5 16h4.5" />
      </svg>
      <span class="drop__title">
        拖拽 <b>{{ formats }}</b> 到此处，或<em>点击选择</em>
      </span>
      <span v-if="hint" class="drop__hint">{{ hint }}</span>
    </button>

    <template v-else>
      <button class="chip" type="button" @click="openPicker">
        <svg
          class="chip__icon"
          viewBox="0 0 24 24"
          width="24"
          height="24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
          focusable="false"
        >
          <path d="M13.5 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7.5z" />
          <path d="M13.5 3v4.5H18" />
          <path d="M8.5 12.5h7M8.5 16h4.5" />
        </svg>
        <span class="chip__meta">
          <span class="chip__name">{{ file.name }}</span>
          <span class="chip__sub">{{ sizeText }} · 点击或拖入可替换</span>
        </span>
      </button>
      <button class="chip__remove" type="button" aria-label="移除文件" @click="file = null">
        <svg
          viewBox="0 0 24 24"
          width="16"
          height="16"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          aria-hidden="true"
          focusable="false"
        >
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </template>
  </div>
</template>

<style scoped>
.drop {
  position: relative;
  /* 撑满容器：放在 Element 表单项里时父级是 flex，不显式给宽度就会被压成内容宽 */
  width: 100%;
  border: 1px dashed var(--rule-strong);
  border-radius: var(--radius-lg);
  background-color: var(--surface-2);
  transition: border-color var(--dur-fast) var(--ease-out),
    background-color var(--dur-fast) var(--ease-out);
}

/* 已选态撤掉虚线：虚线是"这里还空着"的信号，文件已经在了就不该再喊 */
.drop.is-filled {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding-right: var(--space-2);
  border-style: solid;
  border-color: var(--rule);
  background-color: var(--surface);
}

.drop.is-dragging {
  border-style: solid;
  border-color: var(--accent);
  background-color: var(--accent-wash);
}

/* 键盘焦点落在内部按钮上时，让整个投放区一起响应 */
.drop:has(:focus-visible) {
  border-color: var(--accent);
}

.drop__input {
  display: none;
}

.drop__cta {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  padding: var(--space-6) var(--space-5);
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.drop__icon {
  color: var(--muted);
  transition: transform var(--dur-base) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.drop__cta:hover .drop__icon {
  color: var(--accent);
  transform: translateY(-2px);
}

/* 拖入时图标再抬高一档：让"投放"看起来是被接住了 */
.drop.is-dragging .drop__icon {
  color: var(--accent);
  transform: translateY(-5px);
}

.drop__title {
  font-size: var(--fs-md);
  color: var(--ink-2);
}

.drop__title b {
  font-weight: 600;
  color: var(--ink);
}

/* "点击选择"用下划线扫过提示可点，而不是只换个颜色 */
.drop__title em {
  font-style: normal;
  color: var(--accent);
  background-image: linear-gradient(var(--accent), var(--accent));
  background-repeat: no-repeat;
  background-position: 0 100%;
  background-size: 0 1px;
  transition: background-size var(--dur-base) var(--ease-out);
}

.drop__cta:hover .drop__title em {
  background-size: 100% 1px;
}

.drop__hint {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.chip {
  display: flex;
  align-items: center;
  flex: 1;
  gap: var(--space-3);
  min-width: 0;
  padding: var(--space-4);
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

/* 与空态同一个公文纸图形，只换颜色：两态之间对象不变，变的是状态 */
.chip__icon {
  flex: none;
  color: var(--accent);
}

.chip__meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.chip__name {
  overflow: hidden;
  font-size: var(--fs-md);
  color: var(--ink);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip__sub {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.chip__remove {
  display: grid;
  flex: none;
  place-items: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: var(--radius-md);
  background: none;
  color: var(--muted);
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.chip__remove:hover {
  background-color: var(--accent-wash);
  color: var(--risk);
}

.drop__cta:focus-visible,
.chip:focus-visible,
.chip__remove:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: var(--radius-md);
}

@media (prefers-reduced-motion: reduce) {
  .drop,
  .drop__icon,
  .drop__title em,
  .chip__remove {
    transition: none;
  }
}
</style>
