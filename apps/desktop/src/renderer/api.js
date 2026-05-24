const WORD2PIC_URL = 'http://127.0.0.1:9001/api/v1/generate'
const WORD2PIC_WORKFLOW = 'test_z_image_turbo'

function ensureElectronApi(method) {
  if (!window.artTextApp?.[method]) {
    throw new Error(`Electron 接口 ${method} 不可用，请使用桌面端运行。`)
  }
}

export async function getPlatform() {
  if (window.artTextApp?.getPlatform) {
    return window.artTextApp.getPlatform()
  }
  return navigator.platform || 'unknown'
}

export async function getAppVersion() {
  ensureElectronApi('getAppVersion')
  return window.artTextApp.getAppVersion()
}

export async function isDev() {
  ensureElectronApi('isDev')
  return window.artTextApp.isDev()
}

export async function notify(options) {
  ensureElectronApi('notify')
  return window.artTextApp.notify(options)
}

export async function openExternal(url) {
  ensureElectronApi('openExternal')
  return window.artTextApp.openExternal(url)
}

export async function vectorizeArtImage(payload) {
  ensureElectronApi('vectorize')
  return window.artTextApp.vectorize(payload)
}

export async function generateArtBitmap(payload) {
  if (window.artTextApp?.generate) {
    return window.artTextApp.generate(payload)
  }

  const combinedPrompt = payload.text
    ? `艺术字文本：${payload.text}，风格：${payload.prompt || ''}`
    : (payload.prompt || '')

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
  return {
    png: data.image_base64 || '',
    svg: '',
    metadata: data.metadata || null,
  }
}

export async function saveFile(data, defaultName, filters = []) {
  ensureElectronApi('saveFile')
  return window.artTextApp.saveFile({ data, defaultName, filters })
}

export async function saveResults(results, fileBase) {
  ensureElectronApi('saveResults')
  return window.artTextApp.saveResults({ results, fileBase })
}
