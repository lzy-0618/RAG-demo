<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    /** 印章边长（px） */
    size?: number
    /** seal：只有印章；stacked：印章 + 竖排字标（登录页）；inline：印章 + 横排字标 */
    layout?: 'seal' | 'stacked' | 'inline'
    /** 是否显示「企业合规智能平台」副标题 */
    showCaption?: boolean
  }>(),
  { size: 44, layout: 'seal', showCaption: true },
)

const sealSize = computed(() => ({ width: `${props.size}px`, height: `${props.size}px` }))
</script>

<template>
  <div class="brand" :class="`brand--${props.layout}`">
    <!-- 与 public/favicon.svg 同一构成：朱红方印 + 内层发丝键线 + 宋体字。
         颜色写在 CSS 里而非 SVG 属性上——presentation attribute 不接受 var()。 -->
    <svg class="brand-seal" :style="sealSize" viewBox="0 0 64 64" role="img" aria-label="宝智审">
      <rect class="seal-ground" width="64" height="64" rx="10" />
      <rect class="seal-keyline" x="9.5" y="9.5" width="45" height="45" rx="3" />
      <text class="seal-glyph" x="32" y="43.5" text-anchor="middle">宝</text>
    </svg>

    <div v-if="props.layout !== 'seal'" class="brand-text">
      <p class="brand-name">宝智审</p>
      <p v-if="props.showCaption" class="brand-caption">企业合规智能平台</p>
    </div>
  </div>
</template>

<style scoped>
.brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.brand--stacked {
  flex-direction: column;
  gap: var(--space-4);
  text-align: center;
}

.brand-seal {
  display: block;
  flex: none;
  /* 与 SVG 的 rx=10 对齐，避免不同内核对圆角裁切的差异 */
  border-radius: 8px;
  box-shadow: var(--shadow-1);
}

.seal-ground {
  fill: var(--accent);
}

.seal-keyline {
  fill: none;
  stroke: var(--on-accent);
  stroke-width: 2.5;
  opacity: 0.92;
}

.seal-glyph {
  fill: var(--on-accent);
  font-family: "Songti SC", "Noto Serif CJK SC", "SimSun", serif;
  font-size: 30px;
  font-weight: 600;
}

.brand-name {
  margin: 0;
  font-family: var(--font-serif);
  font-size: var(--fs-xl);
  font-weight: 600;
  line-height: 1.2;
  color: var(--ink);
  /* 字距会在末字后多留一份，靠等量的半值缩进把视觉中线拉回来 */
  letter-spacing: 0.16em;
  text-indent: 0.08em;
}

.brand-caption {
  margin: 6px 0 0;
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  letter-spacing: 0.18em;
  text-indent: 0.09em;
  color: var(--muted);
}

.brand--stacked .brand-name {
  font-size: var(--fs-2xl);
}

.brand--inline .brand-name {
  font-size: var(--fs-lg);
  letter-spacing: 0.1em;
  text-indent: 0.05em;
}

.brand--inline .brand-caption {
  display: none;
}
</style>
