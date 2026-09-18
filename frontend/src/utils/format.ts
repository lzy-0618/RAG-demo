/** 展示层格式化。表格里的时间只到分钟：秒在列表语境里是噪声，
 *  去掉后列宽可收进容器，也避免右侧固定列覆盖内容。 */
export function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  return value.length >= 16 ? value.slice(0, 16) : value
}

/** 文件大小：只到一位小数。模板与审查附件都在几十 MB 以内，更大的单位没有区分度；
 *  不足 1KB 的按 1KB 显示，避免出现"0 KB"。 */
export function formatFileSize(bytes: number): string {
  if (!bytes) return '0 KB'
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}
