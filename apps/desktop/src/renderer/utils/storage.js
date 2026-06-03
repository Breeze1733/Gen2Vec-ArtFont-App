/**
 * 轻量存储工具
 * - 历史记录与任务目录映射统一由 localStorage 维护（见 App.vue）
 * - 本文件只保留缩略图生成（用于历史列表展示）
 */

/**
 * 从 data URL 生成缩略图（宽度 64px，保持比例）
 * @param {string} dataUrl - 原始 data URL
 * @returns {Promise<string>} 缩略图 data URL
 */
export function makeThumbnail(dataUrl) {
  return new Promise((resolve) => {
    if (!dataUrl) return resolve('')

    const img = new Image()
    img.onload = () => {
      const targetW = 64
      const ratio = targetW / img.width
      const targetH = Math.round(img.height * ratio)

      const canvas = document.createElement('canvas')
      canvas.width = targetW
      canvas.height = targetH
      const ctx = canvas.getContext('2d')
      ctx.drawImage(img, 0, 0, targetW, targetH)

      try {
        resolve(canvas.toDataURL('image/jpeg', 0.6))
      } catch {
        resolve('')
      }
    }
    img.onerror = () => resolve('')
    img.src = dataUrl
  })
}
