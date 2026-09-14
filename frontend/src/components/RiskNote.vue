<script setup lang="ts">
/** 风险条目（批注卡）：审查页与生成页共用同一套呈现。
 *  结构 —— 编号 + 等级标记 + 被审查原文引文块 + 脚注式依据/案例/建议。
 *  样式在 styles/patterns.css，组件本身不带样式，避免两处各写一份。 */

interface Violation {
  law_name: string
  article?: string | null
  description: string
}

interface ReferenceCase {
  case_name: string
  lesson: string
}

withDefaults(
  defineProps<{
    index: number
    level: string
    clause: string
    location?: string | null
    violations?: Violation[]
    referenceCase?: ReferenceCase | null
    suggestion?: string | null
  }>(),
  { location: null, violations: () => [], referenceCase: null, suggestion: null },
)

const LEVEL_LABEL: Record<string, string> = {
  high: '高风险',
  medium: '中风险',
  low: '低风险',
}

function levelLabel(level: string) {
  return LEVEL_LABEL[level] ?? level
}
</script>

<template>
  <article class="note" :data-level="level">
    <header class="note-head">
      <span class="note-no u-num">{{ String(index + 1).padStart(2, '0') }}</span>
      <span class="level" :data-level="level">
        <span class="level-dot" aria-hidden="true" />
        {{ levelLabel(level) }}
      </span>
      <span v-if="location" class="note-loc">{{ location }}</span>
    </header>

    <blockquote class="note-clause">{{ clause }}</blockquote>

    <div v-if="violations.length" class="note-block">
      <p class="note-block-title u-caption">违反依据</p>
      <ul class="note-list">
        <li v-for="(v, vi) in violations" :key="vi" class="note-item">
          <span class="note-ref">
            {{ v.law_name }}<template v-if="v.article"> · {{ v.article }}</template>
          </span>
          <span class="note-desc">{{ v.description }}</span>
        </li>
      </ul>
    </div>

    <div v-if="referenceCase" class="note-block">
      <p class="note-block-title u-caption">参考案例</p>
      <div class="note-item no-rule">
        <span class="note-ref">{{ referenceCase.case_name }}</span>
        <span class="note-desc">{{ referenceCase.lesson }}</span>
      </div>
    </div>

    <p v-if="suggestion" class="note-suggest">建议：{{ suggestion }}</p>
  </article>
</template>
