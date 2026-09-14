<script setup lang="ts">
/** 编排线：用等宽编号 + 发丝连接线标示流程位置，替代 Element 的表格化步骤条。
 *  当前节点压一条朱红标记，已完成节点回到墨色，未开始节点弱化。 */
defineProps<{
  steps: string[]
  active: number
}>()
</script>

<template>
  <ol class="flow">
    <li
      v-for="(step, i) in steps"
      :key="step"
      class="flow-node"
      :class="{ 'is-done': i < active, 'is-active': i === active }"
      :aria-current="i === active ? 'step' : undefined"
    >
      <span class="flow-no u-num">{{ String(i + 1).padStart(2, '0') }}</span>
      <span class="flow-label">{{ step }}</span>
    </li>
  </ol>
</template>

<style scoped>
.flow {
  display: flex;
  align-items: stretch;
  margin: 0;
  padding: 0;
  list-style: none;
  border-top: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule);
}

.flow-node {
  position: relative;
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  flex: 1;
  min-width: 0;
  padding: var(--space-3) var(--space-4) var(--space-3) 0;
  color: var(--muted);
}

.flow-node + .flow-node {
  padding-left: var(--space-4);
  border-left: 1px solid var(--rule);
}

.flow-no {
  font-size: var(--fs-2xs);
  letter-spacing: 0.04em;
}

.flow-label {
  font-size: var(--fs-sm);
  letter-spacing: 0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.flow-node.is-done {
  color: var(--ink-2);
}

.flow-node.is-active {
  color: var(--ink);
}

.flow-node.is-active .flow-label {
  font-weight: 600;
}

/* 当前节点的朱红标记压在顶边的规则线上 */
.flow-node.is-active::before {
  content: "";
  position: absolute;
  top: -1px;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--accent);
}

@media (max-width: 640px) {
  .flow {
    flex-direction: column;
  }

  .flow-node + .flow-node {
    padding-left: 0;
    border-left: none;
    border-top: 1px solid var(--rule);
  }

  .flow-node.is-active::before {
    top: 0;
    right: auto;
    bottom: 0;
    width: 2px;
    height: auto;
  }
}
</style>
