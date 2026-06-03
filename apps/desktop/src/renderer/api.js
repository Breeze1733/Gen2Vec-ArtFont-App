/**
 * Renderer-side API wrapper for the Electron preload `window.artTextApp`.
 *
 * This module provides thin wrappers and documentation-friendly names for
 * renderer code to call native capabilities (IPC->main->backend).
 */
const TXT2IMG_URL = 'http://127.0.0.1:9001/api/v1/txt2img'
const VECTORIZER_URL = 'http://127.0.0.1:8000/api/v1/vectorize'
const TXT2IMG_WORKFLOW = ''  // 空字符串 = 使用后端降级链 (Flux → Z-Image → Stub)

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

async function fetchJsonWithTimeout(url, payload, timeoutMs = 120000) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    })

    if (!response.ok) {
      const errBody = await response.json().catch(() => ({}))
      throw new Error(errBody.detail || `后端返回 ${response.status}`)
    }

    return response.json()
  } catch (err) {
    if (err?.name === 'AbortError') {
      throw new Error(`后端请求超时（${Math.round(timeoutMs / 1000)} 秒）`)
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
}

/**
 * Call the vectorize pipeline. It uses direct local HTTP first because large
 * vectorization responses can hang in Electron net proxy on some Windows setups.
 * @param {Object} payload - See docs/electron-ipc.md for schema
 */
export async function vectorizeArtImage(payload) {
  const { __timeoutMs = 120000, ...body } = payload || {}
  try {
    return await fetchJsonWithTimeout(VECTORIZER_URL, body, __timeoutMs)
  } catch (fetchErr) {
    // Keep Electron proxy as a fallback for environments where direct HTTP is blocked.
    if (window.artTextApp?.vectorize) {
      return window.artTextApp.vectorize(payload)
    }
    throw fetchErr
  }
}

/**
 * Generate artwork bitmap. If running in Electron this proxies to main,
 * otherwise it falls back to the local TXT2IMG HTTP endpoint.
 * @param {Object} payload
 * @returns {Promise<{png:string,svg?:string,metadata?:Object}>}
 */
export async function generateArtBitmap(payload) {
  if (window.artTextApp?.generate) {
    const safeFormat = payload.format === 'SVG Only' ? 'PNG' : 'PNG'

    const body = {
      text: payload.text || '',
      prompt: payload.prompt || '',
      negative_prompt: payload.negative || '',
      resolution: payload.resolution || '1024 x 1024',
      seed: payload.seed || 0,
      style: payload.style || 'default',
      format: safeFormat,
      workflow: TXT2IMG_WORKFLOW,
    }

    const data = await window.artTextApp.generate(body)
    return {
      png: data.image_base64 || '',
      image_name: data.image_name || '',
      svg: '',
      metadata: data.metadata || null,
    }
  }

  const safeFormat = payload.format === 'SVG Only' ? 'PNG' : 'PNG'

  const body = {
    text: payload.text || '',
    prompt: payload.prompt || '',
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
 * Prepare a standard outputs/task_xxx directory in the Electron main process.
 * @param {{mode?:string,index?:number,text?:string,seed?:number,outputRoot?:string,usesTxt2Img?:boolean}} options
 */
export async function prepareOutputTask(options) {
  ensureElectronApi('prepareOutputTask')
  return window.artTextApp.prepareOutputTask(options)
}

function toIpcPlainObject(value) {
  // ipcRenderer.invoke uses the structured clone algorithm. Vue proxies and a few
  // browser-native objects can trigger "An object could not be cloned", so normalize
  // payloads before sending them to Electron main.
  return JSON.parse(JSON.stringify(value ?? {}))
}

/**
 * Write fixed-name task artifacts and update batch_summary.csv.
 * @param {Object} options
 */
export async function writeTaskArtifacts(options) {
  ensureElectronApi('writeTaskArtifacts')
  return window.artTextApp.writeTaskArtifacts(toIpcPlainObject(options))
}

/**
 * Read a generated output file through Electron main process.
 * @param {{filePath:string,encoding?:'dataUrl'|'text',mime?:string}} options
 */
export async function readOutputFile(options) {
  ensureElectronApi('readOutputFile')
  return window.artTextApp.readOutputFile(options)
}

/**
 * Delete an output directory through the Electron main process.
 * Only directories under the configured outputs root are allowed.
 * @param {string} targetPath
 */
export async function deleteOutputDir(targetPath) {
  ensureElectronApi('deleteOutputDir')
  return window.artTextApp.deleteOutputDir(targetPath)
}

/**
 * Open a local file-system path with the operating system.
 * @param {string} targetPath
 */
export async function openPath(targetPath) {
  ensureElectronApi('openPath')
  return window.artTextApp.openPath(targetPath)
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
