const { app, BrowserWindow, ipcMain, dialog, net, shell, Notification } = require('electron')
const path = require('path')
const fs = require('fs/promises')
const fsSync = require('fs')

// 强制 Windows 使用高性能独立显卡（NVIDIA/AMD），避免默认分配集显导致 WebGL 检测不到独显
// 必须在 app.whenReady() 之前调用
// 注：部分 Electron 版本下 commandLine 可能未就绪，包裹 try/catch 作为尽力而为的优化
try {
  if (app && app.commandLine) {
    app.commandLine.appendSwitch('force_high_performance_gpu')
  }
} catch (_) {
  // 非关键路径，静默忽略
}

const VECTORIZER_BACKEND_URL = process.env.VECTORIZER_BACKEND_URL || 'http://127.0.0.1:8000/api/v1/vectorize'
const TXT2IMG_BACKEND_URL = process.env.TXT2IMG_BACKEND_URL || 'http://127.0.0.1:9001/api/v1/txt2img'

function createWindow() {
  const win = new BrowserWindow({
    width: 1080,
    height: 760,
    minWidth: 920,
    minHeight: 640,
    title: '矢量艺术字生成器',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false
    }
  })

  // 窗口准备好后最大化显示
  win.once('ready-to-show', () => {
    win.maximize()
    win.show()
  })

  if (process.env.VITE_DEV_SERVER_URL) {
    win.loadURL(process.env.VITE_DEV_SERVER_URL)
    win.webContents.openDevTools({ mode: 'detach' })
    return
  }

  win.loadFile(path.join(__dirname, '../dist/index.html'))
}

function parseDataUrl(dataUrl) {
  const match = /^data:(.+?)(;base64)?,(.*)$/s.exec(dataUrl)
  if (!match) {
    return Buffer.from(dataUrl, 'utf8')
  }

  const isBase64 = !!match[2]
  const data = match[3]
  return isBase64 ? Buffer.from(data, 'base64') : Buffer.from(decodeURIComponent(data), 'utf8')
}

function getOutputRoot() {
  if (process.env.ART_TEXT_OUTPUT_ROOT) {
    return path.resolve(process.env.ART_TEXT_OUTPUT_ROOT)
  }

  const appPath = app.getAppPath()
  // 开发环境下 appPath 通常是 apps/desktop，按项目根目录输出到 outputs/，
  // 与需求文档和验收脚本的目录结构保持一致。
  if (!app.isPackaged && path.basename(appPath) === 'desktop') {
    return path.resolve(appPath, '..', '..', 'outputs')
  }

  // 打包后写入用户文档目录，避免 Program Files 等安装目录无写权限，
  // 也便于用户直接找到并提交 outputs 产物。
  return path.resolve(app.getPath('documents'), 'Gen2Vec-ArtFont-App', 'outputs')
}

function padTaskIndex(index) {
  const safeIndex = Number.isFinite(Number(index)) && Number(index) > 0 ? Number(index) : 1
  return String(Math.trunc(safeIndex)).padStart(3, '0')
}

function transliterateChinese(text) {
  const map = {
    爱: 'ai', 情: 'qing', 海: 'hai', 梨: 'li', 园: 'yuan', 醉: 'zui', 梦: 'meng', 七: 'qi', 里: 'li', 香: 'xiang',
    红: 'hong', 豆: 'dou', 抹: 'mo', 茶: 'cha', 青: 'qing', 山: 'shan', 集: 'ji', 夏: 'xia', 日: 'ri', 冰: 'bing', 饮: 'yin',
    花: 'hua', 朝: 'chao', 节: 'jie', 咖: 'ka', 啡: 'fei', 字: 'zi', 艺: 'yi', 术: 'shu', 文: 'wen', 本: 'ben', 图: 'tu'
  }
  return Array.from(String(text || '')).map((char) => map[char] || char).join('')
}

function safeTaskSlug(text) {
  const transliterated = transliterateChinese(text || 'art-text')
  const slug = transliterated
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-zA-Z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase()
  return (slug || 'art-text').slice(0, 48)
}

function formatTaskStartedAt(startedAt) {
  const date = startedAt ? new Date(startedAt) : new Date()
  const validDate = Number.isNaN(date.getTime()) ? new Date() : date
  const pad = (value, width = 2) => String(value).padStart(width, '0')
  return [
    validDate.getFullYear(),
    pad(validDate.getMonth() + 1),
    pad(validDate.getDate()),
    '_',
    pad(validDate.getHours()),
    pad(validDate.getMinutes()),
    pad(validDate.getSeconds()),
    '_',
    pad(validDate.getMilliseconds(), 3)
  ].join('')
}

async function ensureUniqueTaskDir({ outputRoot, mode = 'single', index = 1, text = 'art-text', seed = 0, startedAt = null, summaryDir = null }) {
  const root = path.resolve(outputRoot || getOutputRoot())
  await fs.mkdir(root, { recursive: true })

  const timestamp = formatTaskStartedAt(startedAt)
  const indexSuffix = mode === 'batch' ? `_${padTaskIndex(index)}` : ''
  const baseName = `task_${timestamp}${indexSuffix}`
  let taskName = baseName
  let taskDir = path.join(root, taskName)
  let counter = 2
  while (fsSync.existsSync(taskDir)) {
    taskName = `${baseName}_${counter}`
    taskDir = path.join(root, taskName)
    counter += 1
  }

  await fs.mkdir(taskDir, { recursive: true })
  return buildTaskInfo({ outputRoot: root, taskDir, taskName, mode, index, seed, summaryDir })
}

function buildTaskInfo({ outputRoot, taskDir, taskName, mode, index, seed, summaryDir }) {
  const summaryRoot = summaryDir || outputRoot
  const paths = {
    original: path.join(taskDir, 'original.png'),
    transparent: path.join(taskDir, 'transparent.png'),
    svg: path.join(taskDir, 'result.svg'),
    preview: path.join(taskDir, 'preview.png'),
    metadata: path.join(taskDir, 'metadata.json'),
    log: path.join(taskDir, 'run.log'),
    workflows: path.join(taskDir, 'workflows'),
    workflowApi: path.join(taskDir, 'workflows', 'workflow_api.json'),
    workflowNodes: path.join(taskDir, 'workflows', 'nodes.md'),
    modelDependencies: path.join(taskDir, 'workflows', 'model_dependencies.json'),
    summary: path.join(summaryRoot, 'batch_summary.csv'),
    summaryDir: summaryRoot
  }
  return { outputRoot, taskDir, taskName, mode, index, seed, paths }
}

function bufferForArtifact(data, isText = false) {
  if (data === undefined || data === null || data === '') return null
  if (Buffer.isBuffer(data)) return data
  if (typeof data === 'object') return Buffer.from(JSON.stringify(data, null, 2), 'utf8')
  const str = String(data)
  if (!isText && str.startsWith('data:')) return parseDataUrl(str)
  return Buffer.from(str, 'utf8')
}

async function writeArtifactFile(filePath, data, isText = false) {
  const buffer = bufferForArtifact(data, isText)
  if (!buffer) return null
  await fs.mkdir(path.dirname(filePath), { recursive: true })
  await fs.writeFile(filePath, buffer)
  return filePath
}

function csvEscape(value) {
  const text = value === undefined || value === null ? '' : String(value)
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`
  return text
}

async function appendBatchSummaryCsv(summaryPath, row = {}) {
  const columns = [
    'task_id', 'task_name', 'mode', 'status', 'text', 'prompt', 'seed', 'resolution', 'task_dir',
    'original_path', 'transparent_path', 'result_svg_path', 'preview_path', 'metadata_path', 'run_log_path', 'error'
  ]
  await fs.mkdir(path.dirname(summaryPath), { recursive: true })
  const exists = fsSync.existsSync(summaryPath)
  const line = columns.map((key) => csvEscape(row[key])).join(',')
  const content = `${exists ? '' : `${columns.join(',')}\n`}${line}\n`
  await fs.appendFile(summaryPath, content, 'utf8')
}

function inferLegacyExt(key, data) {
  const lowerKey = String(key).toLowerCase()
  const str = typeof data === 'string' ? data.trim() : ''
  if (lowerKey === 'svg' || lowerKey.includes('svg') || str.startsWith('<svg')) return 'svg'
  if (lowerKey === 'metadata' || lowerKey.includes('meta') || str.startsWith('{') || str.startsWith('[')) return 'json'
  if (lowerKey.includes('log')) return 'log'
  if (str.startsWith('data:image/') || ['original', 'transparent', 'preview', 'png'].some(k => lowerKey.includes(k))) return 'png'
  if (typeof data === 'string') return 'txt'
  return 'bin'
}

function buildWorkflowArtifacts({ metadata = {}, taskName = '', seed = 0, mode = 'single', workflowApi = null, modelDependencies = null }) {
  if (workflowApi || modelDependencies) {
    return {
      workflowApi: workflowApi || {
        task_name: taskName,
        mode,
        seed,
        workflow: metadata?.generation?.workflow || metadata?.workflow || metadata?.engine || 'local-runtime',
        prompt: metadata?.generation?.prompt || metadata?.prompt || '',
        text: metadata?.generation?.text || '',
        resolution: metadata?.generation?.resolution || '',
        captured_at: new Date().toISOString()
      },
      workflowNodes: `# 工作流节点说明\n\n- 任务：${taskName}\n- 模式：${mode}\n- 文生图：生成位图 original.png\n- 矢量化：生成 transparent.png、result.svg、preview.png\n\n> 当前文件为桌面端运行快照；后续可由 txt2img-api 返回完整 ComfyUI 节点清单。\n`,
      modelDependencies: modelDependencies || {
        engine: metadata?.engine || metadata?.generation?.engine || 'unknown',
        workflow: metadata?.workflow || metadata?.generation?.workflow || null,
        style: metadata?.style || metadata?.generation?.style || null,
        note: '运行时模型依赖快照；请结合交付文档中的模型清单核验。'
      }
    }
  }
  return {
    workflowApi: {
      task_name: taskName,
      mode,
      seed,
      workflow: metadata?.generation?.workflow || metadata?.workflow || metadata?.engine || 'local-runtime',
      prompt: metadata?.generation?.prompt || metadata?.prompt || '',
      text: metadata?.generation?.text || '',
      resolution: metadata?.generation?.resolution || '',
      captured_at: new Date().toISOString()
    },
    workflowNodes: `# 工作流节点说明\n\n- 任务：${taskName}\n- 模式：${mode}\n- 文生图：生成位图 original.png\n- 矢量化：生成 transparent.png、result.svg、preview.png\n\n> 当前文件为桌面端运行快照；后续可由 txt2img-api 返回完整 ComfyUI 节点清单。\n`,
    modelDependencies: {
      engine: metadata?.engine || metadata?.generation?.engine || 'unknown',
      workflow: metadata?.workflow || metadata?.generation?.workflow || null,
      style: metadata?.style || metadata?.generation?.style || null,
      note: '运行时模型依赖快照；请结合交付文档中的模型清单核验。'
    }
  }
}

async function requestBackend(apiUrl, payload) {
  return new Promise((resolve, reject) => {
    let request = null
    let settled = false
    let timer = null

    const finish = (fn, value) => {
      if (settled) return
      settled = true
      if (timer) clearTimeout(timer)
      fn(value)
    }

    try {
      const requestUrl = new URL(apiUrl)
      const { __timeoutMs = 180000, ...backendPayload } = payload || {}
      request = net.request({
        method: 'POST',
        protocol: requestUrl.protocol,
        hostname: requestUrl.hostname,
        port: requestUrl.port,
        path: `${requestUrl.pathname}${requestUrl.search}`
      })

      timer = setTimeout(() => {
        try { request?.abort() } catch {}
        finish(reject, new Error(`后端请求超时（${Math.round(Number(__timeoutMs) / 1000)} 秒）`))
      }, Number(__timeoutMs) || 180000)

      request.setHeader('Content-Type', 'application/json')

      let body = ''
      request.on('response', (response) => {
        response.on('data', (chunk) => {
          body += chunk.toString()
        })
        response.on('end', () => {
          if (response.statusCode >= 200 && response.statusCode < 300) {
            try {
              finish(resolve, JSON.parse(body))
            } catch (err) {
              finish(reject, err)
            }
          } else {
            let detail = ''
            try {
              const parsed = JSON.parse(body)
              if (parsed && typeof parsed.detail === 'string') {
                detail = `: ${parsed.detail}`
              }
            } catch (err) {
              // Non-JSON body is still a valid backend error.
            }
            finish(reject, new Error(`后端服务返回 ${response.statusCode}${detail}`))
          }
        })
      })

      request.on('error', (err) => finish(reject, err))
      request.write(JSON.stringify(backendPayload))
      request.end()
    } catch (err) {
      try { request?.abort() } catch {}
      finish(reject, err)
    }
  })
}

ipcMain.handle('art-text/get-app-version', async () => {
  return app.getVersion()
})

ipcMain.handle('art-text/is-dev', async () => {
  return !app.isPackaged || process.env.NODE_ENV !== 'production'
})

ipcMain.handle('art-text/notify', async (event, options) => {
  const { title = '通知', body = '', silent = false } = options || {}
  if (Notification.isSupported()) {
    new Notification({ title, body, silent }).show()
    return { ok: true }
  }
  throw new Error('系统通知不受支持。')
})

ipcMain.handle('art-text/open-external', async (event, url) => {
  if (!url || typeof url !== 'string') {
    throw new Error('Invalid URL')
  }
  await shell.openExternal(url)
  return { ok: true }
})

ipcMain.handle('art-text/open-path', async (event, targetPath) => {
  if (!targetPath || typeof targetPath !== 'string') {
    throw new Error('Invalid path')
  }
  const errorMessage = await shell.openPath(targetPath)
  if (errorMessage) {
    throw new Error(errorMessage)
  }
  return { ok: true }
})

ipcMain.handle('art-text/prepare-output-task', async (event, options) => {
  const { outputRoot, mode, index, text, seed, startedAt, summaryDir } = options || {}
  return ensureUniqueTaskDir({ outputRoot, mode, index, text, seed, startedAt, summaryDir })
})

ipcMain.handle('art-text/write-task-artifacts', async (event, options) => {
  const {
    outputRoot,
    taskDir,
    taskName,
    paths = {},
    artifacts = {},
    metadata = {},
    runLog = '',
    usesTxt2Img = false,
    workflowArtifacts = null,
    summaryRow = null
  } = options || {}

  if (!taskDir || typeof taskDir !== 'string') {
    throw new Error('taskDir is required')
  }

  const root = path.resolve(outputRoot || path.dirname(taskDir))
  const resolvedTaskDir = path.resolve(taskDir)
  await fs.mkdir(resolvedTaskDir, { recursive: true })

  const targetPaths = {
    original: paths.original || path.join(resolvedTaskDir, 'original.png'),
    transparent: paths.transparent || path.join(resolvedTaskDir, 'transparent.png'),
    svg: paths.svg || path.join(resolvedTaskDir, 'result.svg'),
    preview: paths.preview || path.join(resolvedTaskDir, 'preview.png'),
    metadata: paths.metadata || path.join(resolvedTaskDir, 'metadata.json'),
    log: paths.log || path.join(resolvedTaskDir, 'run.log'),
    workflows: paths.workflows || path.join(resolvedTaskDir, 'workflows'),
    workflowApi: paths.workflowApi || path.join(resolvedTaskDir, 'workflows', 'workflow_api.json'),
    workflowNodes: paths.workflowNodes || path.join(resolvedTaskDir, 'workflows', 'nodes.md'),
    modelDependencies: paths.modelDependencies || path.join(resolvedTaskDir, 'workflows', 'model_dependencies.json'),
    summary: paths.summary || path.join(root, 'batch_summary.csv')
  }

  const savedFiles = []
  for (const [key, filePath] of [
    ['original', targetPaths.original],
    ['transparent', targetPaths.transparent],
    ['svg', targetPaths.svg],
    ['preview', targetPaths.preview]
  ]) {
    const saved = await writeArtifactFile(filePath, artifacts[key], key === 'svg')
    if (saved) savedFiles.push(saved)
  }

  const shouldWriteMetadata = metadata !== undefined && metadata !== null
  const metadataPayload = shouldWriteMetadata
    ? {
        ...(metadata || {}),
        schema_version: metadata?.schema_version || 1,
        task_name: metadata?.task_name || taskName || path.basename(resolvedTaskDir),
        output_dir: resolvedTaskDir,
        paths: {
          original: 'original.png',
          transparent: 'transparent.png',
          svg: 'result.svg',
          preview: 'preview.png',
          metadata: 'metadata.json',
          log: 'run.log'
        },
        workflow_paths: usesTxt2Img
          ? {
              workflow_api: 'workflows/workflow_api.json',
              nodes: 'workflows/nodes.md',
              model_dependencies: 'workflows/model_dependencies.json'
            }
          : null
      }
    : null

  if (shouldWriteMetadata) {
    const metadataSaved = await writeArtifactFile(targetPaths.metadata, metadataPayload, true)
    if (metadataSaved) savedFiles.push(metadataSaved)
  }

  if (runLog !== undefined && runLog !== null && runLog !== '') {
    const logSaved = await writeArtifactFile(targetPaths.log, runLog, true)
    if (logSaved) savedFiles.push(logSaved)
  }

  if (usesTxt2Img) {
    const wfApi = workflowArtifacts?.workflowApi || workflowArtifacts?.workflow_api
    const wfDeps = workflowArtifacts?.modelDependencies || workflowArtifacts?.model_dependencies
    const hasRealData = wfApi && typeof wfApi === 'object' && Object.keys(wfApi).length > 2
    const workflow = hasRealData
      ? workflowArtifacts
      : buildWorkflowArtifacts({ metadata: metadataPayload || {}, taskName, seed: metadataPayload?.generation?.seed, mode: metadataPayload?.mode })
    const wfSaved = await writeArtifactFile(targetPaths.workflowApi, workflow.workflowApi || workflow.workflow_api || {}, true)
    const nodesSaved = await writeArtifactFile(targetPaths.workflowNodes, workflow.workflowNodes || workflow.nodes || '', true)
    const depsSaved = await writeArtifactFile(targetPaths.modelDependencies, workflow.modelDependencies || workflow.model_dependencies || {}, true)
    savedFiles.push(...[wfSaved, nodesSaved, depsSaved].filter(Boolean))
  }

  if (summaryRow) {
    const summaryTarget = summaryRow.summary_path || targetPaths.summary
    if (summaryTarget) {
      await appendBatchSummaryCsv(summaryTarget, {
        ...summaryRow,
        task_name: summaryRow.task_name || taskName || path.basename(resolvedTaskDir),
        task_dir: summaryRow.task_dir || resolvedTaskDir,
        original_path: summaryRow.original_path || targetPaths.original,
        transparent_path: summaryRow.transparent_path || targetPaths.transparent,
        result_svg_path: summaryRow.result_svg_path || targetPaths.svg,
        preview_path: summaryRow.preview_path || targetPaths.preview,
        metadata_path: summaryRow.metadata_path || targetPaths.metadata,
        run_log_path: summaryRow.run_log_path || targetPaths.log
      })
    }
  }

  return { canceled: false, outputRoot: root, taskDir: resolvedTaskDir, taskName: taskName || path.basename(resolvedTaskDir), paths: targetPaths, filePaths: savedFiles }
})

ipcMain.handle('art-text/delete-output-dir', async (event, targetPath) => {
  if (!targetPath || typeof targetPath !== 'string') {
    throw new Error('Invalid path')
  }
  // 安全校验：只允许删除 outputs 根目录下的任务子目录
  const root = getOutputRoot()
  const resolved = path.resolve(targetPath)
  if (!resolved.startsWith(path.resolve(root))) {
    throw new Error('只允许删除 outputs 目录下的任务子目录')
  }
  if (!fsSync.existsSync(resolved)) {
    return { ok: true, existed: false }
  }
  if (!fsSync.statSync(resolved).isDirectory()) {
    throw new Error('目标不是目录')
  }
  await fs.rm(resolved, { recursive: true, force: true })
  return { ok: true, existed: true }
})

ipcMain.handle('art-text/read-output-file', async (event, options) => {
  const { filePath, encoding = 'dataUrl', mime = 'application/octet-stream' } = options || {}
  if (!filePath || typeof filePath !== 'string') {
    throw new Error('filePath is required')
  }
  const buffer = await fs.readFile(filePath)
  if (encoding === 'text') {
    return buffer.toString('utf8')
  }
  return `data:${mime};base64,${buffer.toString('base64')}`
})

ipcMain.handle('art-text/vectorize', async (event, payload) => {
  return requestBackend(VECTORIZER_BACKEND_URL, payload)
})

ipcMain.handle('art-text/generate', async (event, payload) => {
  return requestBackend(TXT2IMG_BACKEND_URL, payload)
})

ipcMain.handle('art-text/save-file', async (event, options) => {
  const win = BrowserWindow.getFocusedWindow()
  const { data, defaultName = 'output', filters = [] } = options || {}
  const { canceled, filePath } = await dialog.showSaveDialog(win, {
    title: '保存文件',
    defaultPath: defaultName,
    filters
  })

  if (canceled || !filePath) {
    return { canceled: true }
  }

  const buffer = parseDataUrl(data)
  await fs.writeFile(filePath, buffer)
  return { canceled: false, filePath }
})

ipcMain.handle('art-text/save-results', async (event, options) => {
  const win = BrowserWindow.getFocusedWindow()
  const { results = {}, fileBase = 'art-text' } = options || {}
  const { canceled, filePaths } = await dialog.showOpenDialog(win, {
    title: '选择保存目录',
    properties: ['openDirectory', 'createDirectory']
  })

  if (canceled || !filePaths || filePaths.length === 0) {
    return { canceled: true }
  }

  const folder = filePaths[0]
  const savedFiles = []

  // 支持任意键的 results，按命名或内容推断文件类型
  for (const [key, data] of Object.entries(results || {})) {
    if (!data) continue

    let ext = 'bin'
    let buffer = null

    try {
      const str = String(data)
      const trimmed = str.trim()
      if (key === 'svg' || trimmed.startsWith('<svg')) {
        ext = 'svg'
        buffer = Buffer.from(str, 'utf8')
      } else if (key === 'metadata' || key.toLowerCase().includes('meta') || (trimmed.startsWith('{') || trimmed.startsWith('['))) {
        ext = 'json'
        buffer = Buffer.from(typeof data === 'string' ? data : JSON.stringify(data, null, 2), 'utf8')
      } else if (trimmed.startsWith('data:image/') || key.toLowerCase().includes('png') || key.toLowerCase().includes('image') || key.toLowerCase().includes('original') || key.toLowerCase().includes('preview') || key.toLowerCase().includes('transparent')) {
        ext = 'png'
        buffer = parseDataUrl(data)
      } else {
        // fallback: try to parse as data URL else write as utf8
        if (typeof data === 'string' && data.startsWith('data:')) {
          ext = 'bin'
          buffer = parseDataUrl(data)
        } else if (typeof data === 'string') {
          ext = 'txt'
          buffer = Buffer.from(data, 'utf8')
        } else {
          ext = 'bin'
          buffer = Buffer.from(JSON.stringify(data), 'utf8')
        }
      }
    } catch (err) {
      continue
    }

    const safeKey = String(key).replace(/[^a-zA-Z0-9_-]+/g, '-') || 'artifact'
    const filePath = path.join(folder, `${fileBase}_${safeKey}.${ext}`)
    await fs.writeFile(filePath, buffer)
    savedFiles.push(filePath)
  }

  return { canceled: false, filePaths: savedFiles }
})

app.whenReady().then(() => {
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
