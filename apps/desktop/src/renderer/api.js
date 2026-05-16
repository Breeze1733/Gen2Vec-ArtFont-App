const WORD2PIC_URL = 'http://127.0.0.1:9001/api/v1/generate'
const WORD2PIC_WORKFLOW = 'test_z_image_turbo'

export async function vectorizeArtImage(payload) {
  if (!window.artTextApp?.vectorize) {
    throw new Error('矢量化模式需要 Electron 后端和 FastAPI 服务，请使用桌面端联调。')
  }
  return window.artTextApp.vectorize(payload)
}

export async function generateArtBitmap(payload) {
  // 合并 text 和 prompt 为 word2pic 的 prompt 字段
  const combinedPrompt = payload.text
    ? `艺术字文本：${payload.text}，风格：${payload.prompt || ''}`
    : (payload.prompt || '')

  // word2pic 只接受 "PNG" 或 "PNG + SVG"
  const safeFormat = payload.format === 'SVG Only' ? 'PNG' : 'PNG'

  const body = {
    prompt: combinedPrompt,
    negative_prompt: payload.negative || '',
    resolution: payload.resolution || '1024 x 1024',
    seed: payload.seed || 0,
    style: payload.style || 'default',
    format: safeFormat,
    workflow: WORD2PIC_WORKFLOW,
  }

  const response = await fetch(WORD2PIC_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const errBody = await response.json().catch(() => ({}))
    throw new Error(errBody.detail || `后端返回 ${response.status}`)
  }

  const data = await response.json()

  // word2pic 返回 {image_base64, image_name, metadata}
  // 前端 App.vue 期望 {png, svg, metadata}
  return {
    png: data.image_base64 || '',
    svg: '',
    metadata: data.metadata || null,
  }
}

export async function saveFile(data, defaultName, filters = []) {
  if (window.artTextApp?.saveFile) {
    return window.artTextApp.saveFile({ data, defaultName, filters })
  }
  throw new Error('Electron 保存接口不可用')
}

export async function saveResults(results, fileBase) {
  if (window.artTextApp?.saveResults) {
    return window.artTextApp.saveResults({ results, fileBase })
  }

  throw new Error('Electron 保存接口不可用')
}
