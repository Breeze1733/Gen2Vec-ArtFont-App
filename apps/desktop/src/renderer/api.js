/**
 * Renderer-side API wrapper for the Electron preload `window.artTextApp`.
 *
 * This module provides thin wrappers and documentation-friendly names for
 * renderer code to call native capabilities (IPC->main->backend).
 */
const TXT2IMG_URL = 'http://127.0.0.1:9001/api/v1/txt2img'
const TXT2IMG_WORKFLOW = 'test_z_image_turbo'

function ensureElectronApi(method) {
  if (!window.artTextApp?.[method]) {
    throw new Error(`Electron 接口 ${method} 不可用，请使用桌面端运行。`)
  }
}

/**
 * Return platform string. When running in Electron this is immediate.
 * @returns {Promise<string>} platform
 */
export async function getPlatform() {
  if (window.artTextApp?.getPlatform) {
    return window.artTextApp.getPlatform()
  }
  return navigator.platform || 'unknown'
}

/**
 * Get application version from main process.
 * @returns {Promise<string>}
 */
export async function getAppVersion() {
  ensureElectronApi('getAppVersion')
  return window.artTextApp.getAppVersion()
}

/**
 * Whether app is running in dev mode.
 * @returns {Promise<boolean>}
 */
export async function isDev() {
  ensureElectronApi('isDev')
  return window.artTextApp.isDev()
}

/**
 * Show a native notification via main process.
 * @param {{title?:string,body?:string,silent?:boolean}} options
 */
export async function notify(options) {
  ensureElectronApi('notify')
  return window.artTextApp.notify(options)
}

/**
 * Open an external URL via the OS default browser.
 * @param {string} url
 */
export async function openExternal(url) {
  ensureElectronApi('openExternal')
  return window.artTextApp.openExternal(url)
}

/**
 * Call the vectorize pipeline (backed by /vectorize).
 * @param {Object} payload - See docs/electron-ipc.md for schema
 */
export async function vectorizeArtImage(payload) {
  ensureElectronApi('vectorize')
  return window.artTextApp.vectorize(payload)
}

/**
 * Generate artwork bitmap. If running in Electron this proxies to main,
 * otherwise it falls back to the local TXT2IMG HTTP endpoint.
 * @param {Object} payload
 * @returns {Promise<{png:string,svg?:string,metadata?:Object}>}
 */
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
    workflow: TXT2IMG_WORKFLOW,
  }

  const response = await fetch(TXT2IMG_URL, {
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

/**
 * Save a single file via native dialog.
 * @param {string} data - data URL or text
 * @param {string} defaultName
 * @param {Array} filters
 */
export async function saveFile(data, defaultName, filters = []) {
  ensureElectronApi('saveFile')
  return window.artTextApp.saveFile({ data, defaultName, filters })
}

/**
 * Save multiple results (PNG/SVG/JSON) into a chosen folder.
 * @param {Object} results
 * @param {string} fileBase
 */
export async function saveResults(results, fileBase) {
  ensureElectronApi('saveResults')
  return window.artTextApp.saveResults({ results, fileBase })
}

/**
 * Return introspection info about the exposed Electron API (if available).
 */
export function listElectronAPIs() {
  if (!window.artTextApp) return { available: false }
  return {
    available: true,
    apiVersion: window.artTextApp.apiVersion || null,
    methods: window.artTextApp.listMethods ? window.artTextApp.listMethods() : Object.keys(window.artTextApp)
  }
}
