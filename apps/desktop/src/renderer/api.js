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
      __timeoutMs: payload.__timeoutMs || undefined,
      text: payload.text || '',
      prompt: payload.prompt || '',
      negative_prompt: payload.negative || '',
      resolution: payload.resolution || '1328 x 1328',
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
      workflow_api: data.workflow_api || null,
      model_dependencies: data.model_dependencies || null,
    }
  }

  const safeFormat = payload.format === 'SVG Only' ? 'PNG' : 'PNG'

  const body = {
    text: payload.text || '',
    prompt: payload.prompt || '',
    negative_prompt: payload.negative || '',
    resolution: payload.resolution || '1328 x 1328',
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
    image_name: data.image_name || '',
    svg: '',
    metadata: data.metadata || null,
    workflow_api: data.workflow_api || null,
    model_dependencies: data.model_dependencies || null,
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

/**
 * 关闭两个后端服务（txt2img-api + vectorizer-api）。
 * 桌面端退出时 Electron 主进程会自动调用，也可通过此函数手动触发。
 * @returns {Promise<{ok: boolean, message: string}>}
 */
export async function shutdownBackends() {
  ensureElectronApi('shutdownBackends')
  return window.artTextApp.shutdownBackends()
}

/**
 * 获取启动状态。
 * @returns {Promise<{ready: boolean, modelsReady: boolean, backendsRunning: boolean, modelsSkipped: boolean}>}
 */
export async function getStartupStatus() {
  if (!window.artTextApp?.getStartupStatus) return { ready: true, modelsReady: true, backendsRunning: true, modelsSkipped: false }
  return window.artTextApp.getStartupStatus()
}

/**
 * 触发模型下载（生产打包模式）。
 * @returns {Promise<{ok: boolean, fail: number}>}
 */
export async function downloadModels() {
  if (!window.artTextApp?.downloadModels) {
    throw new Error('模型下载仅在生产打包版本中可用')
  }
  return window.artTextApp.downloadModels()
}

/**
 * 启动 Windows 验收测试脚本。
 * @returns {Promise<{ok: boolean, path: string}>}
 */
export async function launchAcceptanceTest() {
  ensureElectronApi('launchAcceptanceTest')
  return window.artTextApp.launchAcceptanceTest()
}

/**
 * 监听启动/下载进度事件。
 * @param {Function} callback - 接收进度数据对象
 */
export function onSplashProgress(callback) {
  if (window.artTextApp?.onSplashProgress) {
    window.artTextApp.onSplashProgress(callback)
  }
}

/**
 * 移除启动/下载进度监听器。
 */
export function removeSplashProgressListener() {
  if (window.artTextApp?.removeSplashProgressListener) {
    window.artTextApp.removeSplashProgressListener()
  }
}

/**
 * 扫描文件系统历史（tasks-index.json），发现 CLI 等外部工具产生的产物。
 * @param {string} [outputRoot] - 可选的输出根目录，不传则用默认
 * @returns {Promise<Array>} 任务索引条目数组
 */
export async function scanFsHistory(outputRoot) {
  if (window.artTextApp?.scanFsHistory) {
    return window.artTextApp.scanFsHistory(outputRoot || '')
  }
  return []
}

/**
 * 解析批量输入文本（与 CLI batch.mjs 逻辑一致）。
 * 支持 | \t , 分隔、CSV 引号转义、表头检测。
 * @param {string} content - 批量输入文本
 * @returns {Promise<Array<{text:string, prompt:string, negative:string, seed:string, resolution:string}>>}
 */
export async function parseBatchInput(content) {
  if (window.artTextApp?.parseBatchInput) {
    return window.artTextApp.parseBatchInput(content)
  }

  const splitDelimitedLine = (line, delimiter = ',') => {
    const values = []
    let current = ''
    let quoted = false
    for (let i = 0; i < line.length; i++) {
      const char = line[i]
      const next = line[i + 1]
      if (char === '"' && quoted && next === '"') { current += '"'; i += 1 }
      else if (char === '"') quoted = !quoted
      else if (char === delimiter && !quoted) { values.push(current.trim()); current = '' }
      else current += char
    }
    values.push(current.trim())
    return values
  }

  const normalizeBatchItem = (item) => {
    const raw = item || {}
    return {
      text: String(raw.text ?? raw.title ?? raw.word ?? raw.content ?? '').trim(),
      prompt: String(raw.prompt ?? raw.style ?? raw.description ?? '').trim(),
      negative: String(raw.negative ?? raw.negative_prompt ?? '').trim(),
      seed: raw.seed === undefined || raw.seed === '' ? '' : String(raw.seed),
      resolution: raw.resolution ? String(raw.resolution).trim() : '',
    }
  }

  const trimmed = String(content || '').trim()
  if (!trimmed) return []
  if (trimmed.startsWith('[') || trimmed.startsWith('{')) {
    const parsed = JSON.parse(trimmed)
    const rows = Array.isArray(parsed) ? parsed : (Array.isArray(parsed.items) ? parsed.items : [])
    return rows.map(normalizeBatchItem).filter(item => item.text || item.prompt)
  }

  const normalizeLine = (line) => String(line || '')
    .replace(/\uFEFF/g, '')
    .replace(/\uFF5C/g, '|')
    .replace(/\t\|/g, '|')
    .replace(/\|\t/g, '|')
    .trim()
  const lines = trimmed.split(/\r?\n/).map(normalizeLine).filter(line => line && !line.startsWith('#'))
  if (!lines.length) return []

  const first = lines[0].toLowerCase()
  const hasHeader = /\btext\b/.test(first) && /\bprompt\b/.test(first)
  const rows = hasHeader ? lines.slice(1) : lines
  const headerDelimiter = lines[0].includes('|') ? '|' : (lines[0].includes('\t') ? '\t' : ',')
  const headers = hasHeader ? splitDelimitedLine(lines[0], headerDelimiter).map(name => name.trim().toLowerCase()) : []

  return rows.map((line) => {
    const delimiter = line.includes('|') ? '|' : (line.includes('\t') ? '\t' : ',')
    const parts = splitDelimitedLine(line, delimiter)
    if (headers.length > 0) {
      const record = {}
      headers.forEach((key, i) => { record[key] = parts[i] || '' })
      return normalizeBatchItem(record)
    }
    return normalizeBatchItem({
      text: parts[0] || '',
      prompt: parts[1] || '',
      negative: parts[2] || '',
      seed: parts[3] || '',
      resolution: parts[4] || '',
    })
  }).filter(item => item.text || item.prompt)
}
