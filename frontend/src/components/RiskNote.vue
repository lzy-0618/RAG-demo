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

interface Citation {
  document_name: string
  section: string
  url: string
}

withDefaults(
  defineProps<{
    index: number
    level: string
    clause: string
    location?: string | null
    violations?: Violation[]
    analysis?: string | null
    citations?: Citation[]
    caseAnalysis?: string | null
    needsReview?: boolean
    validationNotes?: string[]
    referenceCase?: ReferenceCase | null
    suggestion?: string | null
  }>(),
  { location: null, violations: () => [], analysis: null, citations: () => [], caseAnalysis: null, needsReview: false, validationNotes: () => [], referenceCase: null, suggestion: null },
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

    <div v-if="needsReview" class="note-block">
      <p class="note-block-title u-caption">待人工复核</p>
      <ul class="note-list">
        <li v-for="(note, ni) in validationNotes" :key="ni" class="note-item">{{ note }}</li>
      </ul>
    </div>

    <p v-if="analysis" class="note-suggest">分析：{{ analysis }}</p>

    <div v-if="citations.length" class="note-block">
      <p class="note-block-title u-caption">依据引用</p>
      <ul class="note-list">
        <li v-for="(citation, ci) in citations" :key="ci" class="note-item">
          <a v-if="citation.url" :href="citation.url" target="_blank" rel="noopener noreferrer">
            {{ citation.document_name }} · {{ citation.section }}
          </a>
          <span v-else>{{ citation.document_name }} · {{ citation.section }}（知识库未提供链接）</span>
        </li>
      </ul>
    </div>

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

    <p v-if="caseAnalysis" class="note-suggest">案例分析：{{ caseAnalysis }}</p>

    <p v-if="suggestion" class="note-suggest">建议：{{ suggestion }}</p>
  </article>
</template>
