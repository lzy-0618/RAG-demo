<script setup lang="ts">
/** 导航图标：按「对象 × 动作」构图，让图标携带信息而不是做装饰。
 *
 *  对象 —— 单页 = 合同，书册 = 规章制度
 *  动作 —— 放大镜 = 审查，加号 = 生成
 *  因此「合同审查 / 规章制度审查」成对可辨，「合同生成 / 规章制度生成」同理。
 *  24 网格、1.5 描边、currentColor：随导航项的当前状态自动变色。
 */
defineProps<{ name: string }>()
</script>

<template>
  <svg
    viewBox="0 0 24 24"
    width="18"
    height="18"
    fill="none"
    stroke="currentColor"
    stroke-width="1.5"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <!-- 智能问答：对话气泡 -->
    <path
      v-if="name === 'chat'"
      d="M4 5.5h16a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-5.5l-5 4.5v-4.5H4a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1z"
    />

    <!-- 合同审查：单页 + 放大镜 -->
    <template v-else-if="name === 'contract-review'">
      <path d="M4.5 8.5h6.5a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4.5a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1z" />
      <path d="M6 12h4M6 15h4" />
      <circle cx="16.5" cy="9" r="3.5" />
      <path d="M19 11.5l2.5 2.5" />
    </template>

    <!-- 规章制度审查：书册 + 放大镜 -->
    <template v-else-if="name === 'regulation-review'">
      <path d="M3.5 9.5h3.5v9.5h-3.5z" />
      <path d="M8.5 9.5h3.5v9.5h-3.5z" />
      <circle cx="16.5" cy="9" r="3.5" />
      <path d="M19 11.5l2.5 2.5" />
    </template>

    <!-- 知识库管理：层叠的库 -->
    <template v-else-if="name === 'knowledge'">
      <path d="M12 3.5l8 4-8 4-8-4z" />
      <path d="M4 12.5l8 4 8-4" />
      <path d="M4 17l8 4 8-4" />
    </template>

    <!-- 合同模板库管理：带分区格的表框，读作「模板 / 表单」 -->
    <template v-else-if="name === 'template'">
      <path d="M3.5 4.5h17v15h-17z" />
      <path d="M3.5 9.5h17" />
      <path d="M9.2 9.5v10M14.8 9.5v10" />
    </template>

    <!-- 合同生成：单页 + 加号 -->
    <template v-else-if="name === 'contract-generate'">
      <path d="M4.5 8.5h6.5a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4.5a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1z" />
      <path d="M6 12h4M6 15h4" />
      <path d="M17 6v6M14 9h6" />
    </template>

    <!-- 规章制度生成：书册 + 加号 -->
    <template v-else-if="name === 'regulation-generate'">
      <path d="M3.5 9.5h3.5v9.5h-3.5z" />
      <path d="M8.5 9.5h3.5v9.5h-3.5z" />
      <path d="M17 6v6M14 9h6" />
    </template>
  </svg>
</template>
