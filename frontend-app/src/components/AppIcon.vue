<script setup lang="ts">
import { computed } from 'vue'

/**
 * App 全站只有这几个字形，手写内联 SVG 比引一整个图标库划算。
 * 统一 24 视框、1.8 描边、圆头圆角，保证一组图标观感一致。
 */
const GLYPHS = {
  account: '<circle cx="12" cy="8" r="3.6"/><path d="M4.8 20c0-3.6 3.2-5.6 7.2-5.6s7.2 2 7.2 5.6"/>',
  lock: '<rect x="4.6" y="10.4" width="14.8" height="9.6" rx="2.4"/><path d="M8.2 10.4V7.9a3.8 3.8 0 0 1 7.6 0v2.5"/>',
  copy: '<rect x="8" y="8" width="12.4" height="12.4" rx="2.4"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  check: '<path d="M4.8 12.7 9.7 17.6 19.4 6.8"/>',
  send: '<path d="M12 19.2V5"/><path d="M5.7 11.3 12 5l6.3 6.3"/>',
  stop: '<rect x="7.4" y="7.4" width="9.2" height="9.2" rx="1.8" fill="currentColor" stroke="none"/>',
  down: '<path d="M5.8 9.6 12 15.8l6.2-6.2"/>',
  plus: '<path d="M12 5.6v12.8"/><path d="M5.6 12h12.8"/>',
  logout: '<path d="M14.6 4.6h3a2 2 0 0 1 2 2v10.8a2 2 0 0 1-2 2h-3"/><path d="M10.2 8.4 13.8 12l-3.6 3.6"/><path d="M3.8 12h9.8"/>',
} as const

const props = withDefaults(defineProps<{ name: keyof typeof GLYPHS; size?: number }>(), { size: 20 })

const glyph = computed(() => GLYPHS[props.name] ?? '')
</script>

<template>
  <svg
    class="icon"
    :width="props.size"
    :height="props.size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <g v-html="glyph" />
  </svg>
</template>

<style scoped>
.icon {
  display: block;
  flex: none;
}
</style>
