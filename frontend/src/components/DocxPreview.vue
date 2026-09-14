<script setup lang="ts">
/** 文档预览：展示后端渲染好的逐页 PNG。
 *
 * docx→PDF（LibreOffice）与 PDF→PNG（PyMuPDF）都在后端完成，含中文字形自检；
 * 前端只做分页、缩放与滚动同步，因此不受浏览器 PDF 字体处理差异影响。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { fetchPreviewImage, fetchPreviewMeta } from '@/api/preview'
import type { PreviewPage } from '@/api/preview'

const props = withDefaults(defineProps<{ path: string; minHeight?: string }>(), {
  minHeight: '420px',
})

// 1pt = 96/72 CSS px，让 zoom=1 时预览接近屏幕实际大小
const PT_TO_PX = 96 / 72
const MIN_ZOOM = 0.4
const MAX_ZOOM = 3

const pages = ref<PreviewPage[]>([])
const images = ref<Record<number, string>>({})
const loading = ref(false)
const rendering = ref(false)
const error = ref('')
const currentPage = ref(1)
const zoom = ref(1)
const fitWidth = ref(true)
const hostEl = ref<HTMLElement | null>(null)

const pageCount = computed(() => pages.value.length)
const zoomLabel = computed(() => `${Math.round(zoom.value * 100)}%`)
const pageWidth = computed(() => {
  const first = pages.value[0]
  return first ? Math.round(first.width * PT_TO_PX * zoom.value) : 0
})

function revokeImages() {
  Object.values(images.value).forEach((url) => URL.revokeObjectURL(url))
  images.value = {}
}

async function load() {
  loading.value = true
  error.value = ''
  rendering.value = false
  pages.value = []
  revokeImages()
  currentPage.value = 1
  try {
    const meta = await fetchPreviewMeta(props.path)
    pages.value = meta.data?.pages ?? []
    if (!pages.value.length) return
    rendering.value = true
    const loaded: Record<number, string> = {}
    for (const page of pages.value) {
      loaded[page.page] = await fetchPreviewImage(`${props.path}/${page.page}`)
    }
    images.value = loaded
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : '预览加载失败'
  } finally {
    rendering.value = false
    loading.value = false
    if (fitWidth.value) applyFitWidth()
  }
}

/** 按容器宽度换算 zoom，保证长边贴合可视区 */
function applyFitWidth() {
  const host = hostEl.value
  const first = pages.value[0]
  if (!host || !first) return
  const available = Math.max(host.clientWidth - 24, 240)
  zoom.value = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, available / (first.width * PT_TO_PX)))
}

function setZoom(next: number) {
  fitWidth.value = false
  zoom.value = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, next))
}

function useFitWidth() {
  fitWidth.value = true
  applyFitWidth()
}

function goToPage(pageNo: number) {
  const target = Math.max(1, Math.min(pageCount.value, pageNo))
  currentPage.value = target
  document
    .getElementById(`${containerId}-p${target}`)
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const containerId = `docx-preview-${Math.random().toString(36).slice(2, 9)}`

/** 滚动时同步页码指示 */
function onScroll() {
  const host = hostEl.value
  if (!host) return
  const top = host.getBoundingClientRect().top
  let nearest = 1
  pages.value.forEach((page) => {
    const el = document.getElementById(`${containerId}-p${page.page}`)
    if (el && el.getBoundingClientRect().top - top <= 40) nearest = page.page
  })
  currentPage.value = nearest
}

watch(() => props.path, load, { immediate: true })

onBeforeUnmount(revokeImages)
</script>

<template>
  <div class="preview">
    <div class="toolbar">
      <el-button-group>
        <el-button size="small" :disabled="currentPage <= 1" @click="goToPage(currentPage - 1)">
          上一页
        </el-button>
        <el-button size="small" :disabled="currentPage >= pageCount" @click="goToPage(currentPage + 1)">
          下一页
        </el-button>
      </el-button-group>
      <span class="hint u-num">
        <template v-if="pageCount">{{ currentPage }} / {{ pageCount }} 页</template>
        <template v-else>—</template>
      </span>
      <el-button-group>
        <el-button size="small" @click="setZoom(zoom - 0.1)">－</el-button>
        <el-button size="small" @click="setZoom(zoom + 0.1)">＋</el-button>
      </el-button-group>
      <span class="hint u-num">{{ zoomLabel }}</span>
      <el-button size="small" :type="fitWidth ? 'primary' : 'default'" @click="useFitWidth">
        适应宽度
      </el-button>
      <el-button size="small" text :loading="loading" @click="load">重新加载</el-button>
      <span v-if="rendering" class="hint">正在加载图片…</span>
    </div>

    <el-alert
      v-if="error"
      class="error"
      type="error"
      :closable="false"
      title="预览不可用"
      :description="error"
      show-icon
    />

    <div
      ref="hostEl"
      v-loading="loading"
      class="viewport"
      :style="{ minHeight: props.minHeight }"
      @scroll.passive="onScroll"
    >
      <div
        v-for="page in pages"
        :id="`${containerId}-p${page.page}`"
        :key="page.page"
        class="page"
        :style="{ width: `${pageWidth}px` }"
      >
        <img v-if="images[page.page]" :src="images[page.page]" :alt="`第 ${page.page} 页`" />
        <div v-else class="placeholder" :style="{ height: `${pageWidth * (page.height / page.width)}px` }" />
        <span class="page-no u-num">第 {{ page.page }} / {{ pageCount }} 页</span>
      </div>
      <el-empty v-if="!pageCount && !loading && !error" description="暂无预览内容" />
    </div>
  </div>
</template>

<style scoped>
.preview {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
  margin-bottom: var(--space-3);
}

/* .hint 由 styles/patterns.css 提供，此处不再重复定义 */

.error {
  margin-bottom: var(--space-3);
}

/* 文档视口：暖墨底 + 内阴影，让纸张从背景里浮起来 */
.viewport {
  flex: 1;
  min-height: 0;
  padding: var(--space-4);
  border-radius: var(--radius-md);
  background: var(--viewer-bg);
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.28), inset 0 2px 12px rgba(0, 0, 0, 0.25);
  overflow: auto;
}

.page {
  position: relative;
  margin: 0 auto var(--space-4);
  background: var(--surface);
  box-shadow: var(--shadow-2);
}

.page img {
  display: block;
  width: 100%;
  height: auto;
}

.placeholder {
  background: var(--surface-2);
}

.page-no {
  position: absolute;
  right: var(--space-2);
  bottom: var(--space-1);
  padding: 0 var(--space-1);
  border-radius: var(--radius-sm);
  font-size: var(--fs-xs);
  color: var(--muted);
  background: rgba(255, 255, 255, 0.85);
}
</style>
