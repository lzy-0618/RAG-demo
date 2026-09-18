/** 展示层格式化。表格里的时间只到分钟：秒在列表语境里是噪声，
 *  去掉后列宽可收进容器，也避免右侧固定列覆盖内容。 */
export function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  return value.length >= 16 ? value.slice(0, 16) : value
}
