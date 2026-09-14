import { onBeforeUnmount, ref } from 'vue'

/** 视口断点。用于按宽度决定表格渲染哪些列。
 *
 *  不能用 CSS 隐藏单元格：Element 的表格列宽由 JS 依据列定义计算并写进 colgroup，
 *  单方面 display:none 会让剩余列与表头错位，只能条件渲染整列。
 */
export function useMediaQuery(query: string) {
  const matches = ref(false)

  if (typeof window !== 'undefined' && window.matchMedia) {
    const mql = window.matchMedia(query)
    matches.value = mql.matches
    const onChange = (event: MediaQueryListEvent) => {
      matches.value = event.matches
    }
    mql.addEventListener('change', onChange)
    onBeforeUnmount(() => mql.removeEventListener('change', onChange))
  }

  return matches
}
